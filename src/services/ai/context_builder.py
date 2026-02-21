from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings
from src.core.enums import SignalType
from src.core.types import (
    AITradingContext,
    CandlePoint,
    IndicatorPoint,
    MarketContext,
    OrderBookSnapshot,
    RecentBotPerformance,
    Signal,
)
from src.db.models import AIDecisionModel, PerformanceMetricsModel, SignalModel

_FORBIDDEN_KEYS = {"private", "secret", "passphrase", "api_key", "authorization"}
_HEX_PATTERN = re.compile(r"0x[0-9a-fA-F]{40,}")


class ContextBuilder:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http_client = httpx.AsyncClient(timeout=8.0, http2=True)

    async def close(self) -> None:
        await self._http_client.aclose()

    async def build(
        self,
        *,
        signal_id: int,
        signal: Signal,
        market_context: MarketContext,
        now_utc: datetime,
        session: AsyncSession,
    ) -> AITradingContext:
        candle_history = await self._fetch_candles_history(self._settings.ai_candle_history_count)
        indicator_history = await self._fetch_indicator_history(session, self._settings.ai_candle_history_count)
        performance_7d = await self._fetch_performance_7d(session)

        target_market_price = market_context.up_price
        if signal.signal_type == SignalType.SHORT:
            target_market_price = market_context.down_price

        context = AITradingContext(
            signal_id=signal_id,
            signal_type=signal.signal_type,
            signal_reason=self._sanitize_str(signal.reason),
            candle_open_utc=signal.indicator_snapshot.candle_open_utc,
            market_slug=self._sanitize_str(market_context.market_slug),
            market_end_time=market_context.market_end_time,
            orderbook=OrderBookSnapshot(
                up_price=market_context.up_price,
                down_price=market_context.down_price,
                spread=market_context.spread,
                depth_up=Decimal("0"),
                depth_down=Decimal("0"),
            ),
            target_market_price=target_market_price,
            candle_history=tuple(candle_history),
            indicator_history=tuple(indicator_history),
            performance_7d=performance_7d,
            hour_of_day_utc=now_utc.hour,
            day_of_week_utc=now_utc.strftime("%A"),
        )
        self._assert_no_secrets(context)
        return context

    async def _fetch_candles_history(self, count: int) -> list[CandlePoint]:
        url = "https://api.binance.com/api/v3/klines"
        response = await self._http_client.get(
            url,
            params={"symbol": "BTCUSDT", "interval": "1h", "limit": count},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            return []

        candles: list[CandlePoint] = []
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                continue
            open_ts = int(row[0])
            open_price = Decimal(str(row[1]))
            high_price = Decimal(str(row[2]))
            low_price = Decimal(str(row[3]))
            close_price = Decimal(str(row[4]))
            volume = Decimal(str(row[5]))
            direction = "UP" if close_price >= open_price else "DOWN"
            pct_change = Decimal("0")
            if open_price > 0:
                pct_change = ((close_price - open_price) / open_price) * Decimal("100")

            candles.append(
                CandlePoint(
                    open_time_utc=datetime.fromtimestamp(open_ts / 1000, tz=timezone.utc),
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                    direction=direction,
                    pct_change=pct_change.quantize(Decimal("0.0001")),
                )
            )
        return candles

    async def _fetch_indicator_history(self, session: AsyncSession, count: int) -> list[IndicatorPoint]:
        query = (
            select(SignalModel)
            .order_by(SignalModel.candle_open_utc.desc())
            .limit(count)
        )
        rows = list((await session.execute(query)).scalars().all())
        rows.reverse()

        points: list[IndicatorPoint] = []
        for row in rows:
            points.append(
                IndicatorPoint(
                    candle_open_utc=row.candle_open_utc,
                    rsi=Decimal(str(row.rsi_curr)),
                    stoch_k=Decimal(str(row.stoch_k_curr)),
                    stoch_d=Decimal(str(row.stoch_d_curr)),
                )
            )
        return points

    async def _fetch_performance_7d(self, session: AsyncSession) -> RecentBotPerformance:
        since_date = datetime.now(tz=timezone.utc).date() - timedelta(days=7)
        since_dt = datetime.now(tz=timezone.utc) - timedelta(days=7)

        metrics_query = select(PerformanceMetricsModel).where(PerformanceMetricsModel.metric_date >= since_date)
        metrics = list((await session.execute(metrics_query)).scalars().all())

        total_trades = sum(item.total_trades for item in metrics)
        net_pnl = sum((Decimal(str(item.net_pnl_usdc)) for item in metrics), Decimal("0"))

        wins = sum(item.wins for item in metrics)
        losses = sum(item.losses for item in metrics)
        denominator = wins + losses
        win_rate = Decimal("0") if denominator == 0 else Decimal(wins) / Decimal(denominator)

        ai_total_query = select(func.count()).select_from(AIDecisionModel).where(AIDecisionModel.evaluated_at >= since_dt)
        ai_total = int((await session.execute(ai_total_query)).scalar_one())

        ai_veto_query = select(func.count()).select_from(AIDecisionModel).where(
            and_(AIDecisionModel.evaluated_at >= since_dt, AIDecisionModel.proceed.is_(False))
        )
        ai_veto = int((await session.execute(ai_veto_query)).scalar_one())
        ai_veto_rate = Decimal("0") if ai_total == 0 else Decimal(ai_veto) / Decimal(ai_total)

        return RecentBotPerformance(
            win_rate=win_rate.quantize(Decimal("0.0001")),
            net_pnl_usdc=net_pnl,
            total_trades=total_trades,
            ai_veto_rate=ai_veto_rate.quantize(Decimal("0.0001")),
            ai_total_decisions=ai_total,
        )

    @staticmethod
    def _sanitize_str(value: str) -> str:
        return _HEX_PATTERN.sub("[REDACTED]", value)

    def _assert_no_secrets(self, context: AITradingContext) -> None:
        payload = asdict(context)
        self._scan_keys(payload)
        serialized = json.dumps(payload, default=str)
        if _HEX_PATTERN.search(serialized):
            raise ValueError("Potential secret detected in AI context payload")

    def _scan_keys(self, payload: Any, path: str = "") -> None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                key_lc = str(key).lower()
                if any(marker in key_lc for marker in _FORBIDDEN_KEYS):
                    raise ValueError(f"Forbidden key in AI context: {path}.{key}")
                self._scan_keys(value, path=f"{path}.{key}" if path else str(key))
        elif isinstance(payload, list):
            for index, value in enumerate(payload):
                self._scan_keys(value, path=f"{path}[{index}]")
