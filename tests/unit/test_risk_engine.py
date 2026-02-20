from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.config.settings import Settings
from src.core.enums import SignalType
from src.core.exceptions import RiskVetoError
from src.core.types import IndicatorSnapshot, MarketContext, Signal
from src.services.risk.kill_switch import KillSwitch
from src.services.risk.position_tracker import PositionTracker
from src.services.risk.risk_engine import RiskEngine


class FakeTradeRepo:
    def __init__(self, *, trades_today: int = 0, open_positions: int = 0, daily_pnl: Decimal = Decimal("0")) -> None:
        self._trades_today = trades_today
        self._open_positions = open_positions
        self._daily_pnl = daily_pnl

    async def count_trades_for_day(self, day):  # noqa: ANN001
        del day
        return self._trades_today

    async def count_open_positions(self) -> int:
        return self._open_positions

    async def sum_daily_pnl(self, day):  # noqa: ANN001
        del day
        return self._daily_pnl


def _signal() -> Signal:
    now = datetime.now(tz=timezone.utc)
    snapshot = IndicatorSnapshot(
        evaluated_at=now,
        candle_open_utc=now.replace(minute=0, second=0, microsecond=0),
        rsi_prev=Decimal("20"),
        rsi_curr=Decimal("40"),
        stoch_k_prev=Decimal("10"),
        stoch_d_prev=Decimal("12"),
        stoch_k_curr=Decimal("15"),
        stoch_d_curr=Decimal("13"),
    )
    return Signal(signal_type=SignalType.LONG, reason="test", indicator_snapshot=snapshot)


def _market(now: datetime) -> MarketContext:
    return MarketContext(
        market_slug="btc-hourly",
        condition_id="cond",
        token_id_up="up",
        token_id_down="down",
        spread=Decimal("0.01"),
        tick_size=Decimal("0.01"),
        market_end_time=now + timedelta(minutes=20),
        resolution_source="binance",
    )


@pytest.mark.asyncio
async def test_risk_engine_approves_trade() -> None:
    settings = Settings()
    kill_switch = KillSwitch()
    tracker = PositionTracker()
    engine = RiskEngine(settings, kill_switch, tracker)

    now = datetime.now(tz=timezone.utc)
    approved = await engine.approve_trade(
        signal=_signal(),
        market_context=_market(now),
        now_utc=now,
        trade_repo=FakeTradeRepo(),
    )

    assert approved == Decimal("10.00")


@pytest.mark.asyncio
async def test_risk_engine_veto_daily_limit() -> None:
    settings = Settings(risk_max_trades_per_day=1)
    kill_switch = KillSwitch()
    tracker = PositionTracker()
    engine = RiskEngine(settings, kill_switch, tracker)

    now = datetime.now(tz=timezone.utc)

    with pytest.raises(RiskVetoError, match="Daily trade count limit reached"):
        await engine.approve_trade(
            signal=_signal(),
            market_context=_market(now),
            now_utc=now,
            trade_repo=FakeTradeRepo(trades_today=1),
        )
