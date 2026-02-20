from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings
from src.db.models import SignalModel, TradeModel
from src.db.repository import PerformanceRepo


class PerformanceAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def analyze_day(self, *, metric_day: date, session: AsyncSession):
        start = datetime(metric_day.year, metric_day.month, metric_day.day, tzinfo=timezone.utc)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)

        trades_query = select(TradeModel).where(
            and_(TradeModel.candle_open_utc >= start, TradeModel.candle_open_utc <= end)
        )
        trades = list((await session.execute(trades_query)).scalars().all())

        total_trades = len(trades)
        wins = sum(1 for trade in trades if (trade.pnl_usdc or Decimal("0")) > 0)
        losses = sum(1 for trade in trades if (trade.pnl_usdc or Decimal("0")) <= 0)
        win_rate = Decimal("0") if total_trades == 0 else Decimal(wins) / Decimal(total_trades)

        pnls = [Decimal(str(trade.pnl_usdc or 0)) for trade in trades]
        fees = [Decimal(str(trade.fees_usdc or 0)) for trade in trades]

        gross_pnl = sum(pnls, Decimal("0"))
        total_fees = sum(fees, Decimal("0"))
        net_pnl = gross_pnl - total_fees

        max_drawdown = self._max_drawdown(pnls)

        signals_generated_query = select(func.count()).select_from(SignalModel).where(
            and_(SignalModel.candle_open_utc >= start, SignalModel.candle_open_utc <= end)
        )
        signals_generated = int((await session.execute(signals_generated_query)).scalar_one())

        signals_filtered_query = select(func.count()).select_from(SignalModel).where(
            and_(
                SignalModel.candle_open_utc >= start,
                SignalModel.candle_open_utc <= end,
                SignalModel.filter_result.is_not(None),
            )
        )
        signals_filtered = int((await session.execute(signals_filtered_query)).scalar_one())

        avg_spread_query = select(func.avg(SignalModel.spread_at_eval)).where(
            and_(SignalModel.candle_open_utc >= start, SignalModel.candle_open_utc <= end)
        )
        avg_spread_raw = (await session.execute(avg_spread_query)).scalar_one_or_none()
        avg_spread = Decimal(str(avg_spread_raw)) if avg_spread_raw is not None else None

        repo = PerformanceRepo(session)
        return await repo.upsert_metric(
            metric_date=metric_day,
            total_trades=total_trades,
            wins=wins,
            losses=losses,
            win_rate=win_rate.quantize(Decimal("0.0001")),
            gross_pnl_usdc=gross_pnl,
            fees_usdc=total_fees,
            net_pnl_usdc=net_pnl,
            max_drawdown_usdc=max_drawdown,
            signals_generated=signals_generated,
            signals_filtered=signals_filtered,
            avg_spread_at_entry=avg_spread,
            strategy_snapshot=self._settings.snapshot_strategy(),
            risk_snapshot=self._settings.snapshot_risk(),
        )

    @staticmethod
    def _max_drawdown(pnls: list[Decimal]) -> Decimal:
        equity = Decimal("0")
        peak = Decimal("0")
        max_drawdown = Decimal("0")
        for pnl in pnls:
            equity += pnl
            if equity > peak:
                peak = equity
            drawdown = peak - equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        return max_drawdown
