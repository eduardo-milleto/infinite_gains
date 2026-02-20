from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import OrderStatus, ProposalStatus, SignalType, TradingMode
from src.core.types import IndicatorSnapshot, OrderResult
from src.db.models import (
    ConfigHistoryModel,
    MarketSessionModel,
    PerformanceMetricsModel,
    SignalModel,
    TradeModel,
)


class SignalRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        snapshot: IndicatorSnapshot,
        signal_type: SignalType,
        filter_result: str | None,
        market_slug: str,
        spread_at_eval: Decimal | None,
        trading_mode: TradingMode,
    ) -> SignalModel:
        row = SignalModel(
            evaluated_at=snapshot.evaluated_at,
            candle_open_utc=snapshot.candle_open_utc,
            rsi_prev=snapshot.rsi_prev,
            rsi_curr=snapshot.rsi_curr,
            stoch_k_prev=snapshot.stoch_k_prev,
            stoch_d_prev=snapshot.stoch_d_prev,
            stoch_k_curr=snapshot.stoch_k_curr,
            stoch_d_curr=snapshot.stoch_d_curr,
            signal_type=signal_type.value,
            filter_result=filter_result,
            market_slug=market_slug,
            spread_at_eval=spread_at_eval,
            trading_mode=trading_mode.value,
        )
        self.session.add(row)
        await self.session.flush()
        return row


class TradeRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        signal_id: int,
        market_slug: str,
        condition_id: str,
        candle_open_utc: datetime,
        trading_mode: TradingMode,
        order_result: OrderResult,
    ) -> TradeModel:
        row = TradeModel(
            signal_id=signal_id,
            market_slug=market_slug,
            condition_id=condition_id,
            token_id=order_result.token_id,
            direction=order_result.direction.value,
            candle_open_utc=candle_open_utc,
            order_id=order_result.order_id,
            price=order_result.price,
            size_usdc=order_result.size_usdc,
            size_filled_usdc=order_result.size_filled_usdc,
            status=order_result.status.value,
            failure_reason=order_result.failure_reason,
            trading_mode=trading_mode.value,
            raw_order_response=order_result.raw_response,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update_status(
        self,
        trade_id: int,
        status: OrderStatus,
        *,
        size_filled_usdc: Decimal | None = None,
        raw_fill_event: dict[str, object] | None = None,
        pnl_usdc: Decimal | None = None,
        fees_usdc: Decimal | None = None,
        resolved_direction: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        row = await self.session.get(TradeModel, trade_id)
        if row is None:
            return
        row.status = status.value
        if size_filled_usdc is not None:
            row.size_filled_usdc = size_filled_usdc
        if raw_fill_event is not None:
            row.raw_fill_event = raw_fill_event
        if pnl_usdc is not None:
            row.pnl_usdc = pnl_usdc
        if fees_usdc is not None:
            row.fees_usdc = fees_usdc
        if resolved_direction is not None:
            row.resolved_direction = resolved_direction
        if failure_reason is not None:
            row.failure_reason = failure_reason
        await self.session.flush()

    async def update_by_order_id(
        self,
        order_id: str,
        *,
        status: OrderStatus,
        size_filled_usdc: Decimal | None = None,
        raw_fill_event: dict[str, object] | None = None,
        pnl_usdc: Decimal | None = None,
        fees_usdc: Decimal | None = None,
        resolved_direction: str | None = None,
        failure_reason: str | None = None,
    ) -> TradeModel | None:
        query = select(TradeModel).where(TradeModel.order_id == order_id).limit(1)
        row = (await self.session.execute(query)).scalars().first()
        if row is None:
            return None

        row.status = status.value
        if size_filled_usdc is not None:
            row.size_filled_usdc = size_filled_usdc
        if raw_fill_event is not None:
            row.raw_fill_event = raw_fill_event
        if pnl_usdc is not None:
            row.pnl_usdc = pnl_usdc
        if fees_usdc is not None:
            row.fees_usdc = fees_usdc
        if resolved_direction is not None:
            row.resolved_direction = resolved_direction
        if failure_reason is not None:
            row.failure_reason = failure_reason
        await self.session.flush()
        return row

    async def count_trades_for_day(self, day_utc: date) -> int:
        start = datetime(day_utc.year, day_utc.month, day_utc.day, tzinfo=timezone.utc)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
        query = select(func.count()).select_from(TradeModel).where(
            and_(TradeModel.candle_open_utc >= start, TradeModel.candle_open_utc <= end)
        )
        return int((await self.session.execute(query)).scalar_one())

    async def count_open_positions(self) -> int:
        query = select(func.count()).select_from(TradeModel).where(
            TradeModel.status.in_([OrderStatus.SUBMITTED.value, OrderStatus.MATCHED.value, OrderStatus.CONFIRMED.value])
        )
        return int((await self.session.execute(query)).scalar_one())

    async def sum_daily_pnl(self, day_utc: date) -> Decimal:
        start = datetime(day_utc.year, day_utc.month, day_utc.day, tzinfo=timezone.utc)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
        query = select(func.coalesce(func.sum(TradeModel.pnl_usdc), 0)).where(
            and_(TradeModel.candle_open_utc >= start, TradeModel.candle_open_utc <= end)
        )
        result = (await self.session.execute(query)).scalar_one()
        return Decimal(str(result))

    async def get_last_trade_time(self) -> datetime | None:
        query = select(func.max(TradeModel.candle_open_utc))
        return (await self.session.execute(query)).scalar_one()

    async def list_settled_for_day(self, day_utc: date) -> list[TradeModel]:
        start = datetime(day_utc.year, day_utc.month, day_utc.day, tzinfo=timezone.utc)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
        query = select(TradeModel).where(
            and_(TradeModel.candle_open_utc >= start, TradeModel.candle_open_utc <= end)
        )
        rows = (await self.session.execute(query)).scalars().all()
        return list(rows)


class ConfigRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_change(
        self,
        *,
        config_section: str,
        param_key: str,
        old_value: str | None,
        new_value: str,
        changed_by: str,
        proposal_id: str | None,
        justification: str,
        approved_by: str | None = None,
        status: ProposalStatus = ProposalStatus.PENDING,
    ) -> ConfigHistoryModel:
        row = ConfigHistoryModel(
            changed_at=datetime.now(tz=timezone.utc),
            config_section=config_section,
            param_key=param_key,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            approved_by=approved_by,
            proposal_id=proposal_id,
            justification=justification,
            status=status.value,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def set_proposal_status(
        self,
        proposal_id: str,
        *,
        status: ProposalStatus,
        approved_by: str | None,
    ) -> int:
        query = select(ConfigHistoryModel).where(ConfigHistoryModel.proposal_id == proposal_id)
        rows = (await self.session.execute(query)).scalars().all()
        for row in rows:
            row.status = status.value
            row.approved_by = approved_by
        await self.session.flush()
        return len(rows)

    async def list_pending(self) -> list[ConfigHistoryModel]:
        query = select(ConfigHistoryModel).where(ConfigHistoryModel.status == ProposalStatus.PENDING.value)
        rows = (await self.session.execute(query)).scalars().all()
        return list(rows)

    async def get_latest_value(
        self,
        *,
        config_section: str,
        param_key: str,
        status: ProposalStatus | None = None,
    ) -> str | None:
        query = select(ConfigHistoryModel).where(
            ConfigHistoryModel.config_section == config_section,
            ConfigHistoryModel.param_key == param_key,
        )
        if status is not None:
            query = query.where(ConfigHistoryModel.status == status.value)
        query = query.order_by(ConfigHistoryModel.changed_at.desc()).limit(1)
        row = (await self.session.execute(query)).scalars().first()
        return row.new_value if row else None


class PerformanceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_metric(
        self,
        *,
        metric_date: date,
        total_trades: int,
        wins: int,
        losses: int,
        win_rate: Decimal,
        gross_pnl_usdc: Decimal,
        fees_usdc: Decimal,
        net_pnl_usdc: Decimal,
        max_drawdown_usdc: Decimal,
        signals_generated: int,
        signals_filtered: int,
        avg_spread_at_entry: Decimal | None,
        strategy_snapshot: dict[str, str],
        risk_snapshot: dict[str, str],
    ) -> PerformanceMetricsModel:
        row = await self.session.get(PerformanceMetricsModel, metric_date)
        payload = {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "gross_pnl_usdc": gross_pnl_usdc,
            "fees_usdc": fees_usdc,
            "net_pnl_usdc": net_pnl_usdc,
            "max_drawdown_usdc": max_drawdown_usdc,
            "signals_generated": signals_generated,
            "signals_filtered": signals_filtered,
            "avg_spread_at_entry": avg_spread_at_entry,
            "strategy_snapshot": strategy_snapshot,
            "risk_snapshot": risk_snapshot,
        }
        if row is None:
            row = PerformanceMetricsModel(metric_date=metric_date, **payload)
            self.session.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        await self.session.flush()
        return row


class MarketSessionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        candle_open_utc: datetime,
        market_slug: str,
        condition_id: str,
        token_id_up: str,
        token_id_down: str,
        resolution_source: str,
        tick_size: Decimal,
        market_end_time: datetime,
    ) -> MarketSessionModel:
        row = await self.session.get(MarketSessionModel, candle_open_utc)
        if row is None:
            row = MarketSessionModel(
                candle_open_utc=candle_open_utc,
                market_slug=market_slug,
                condition_id=condition_id,
                token_id_up=token_id_up,
                token_id_down=token_id_down,
                resolution_source=resolution_source,
                tick_size=tick_size,
                market_end_time=market_end_time,
            )
            self.session.add(row)
        else:
            row.market_slug = market_slug
            row.condition_id = condition_id
            row.token_id_up = token_id_up
            row.token_id_down = token_id_down
            row.resolution_source = resolution_source
            row.tick_size = tick_size
            row.market_end_time = market_end_time
        await self.session.flush()
        return row
