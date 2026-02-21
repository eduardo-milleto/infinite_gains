from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.config.settings import Settings
from src.core.enums import SignalType
from src.core.types import IndicatorSnapshot
from src.services.indicators.signal_engine import SignalEngine


def _snapshot(
    *,
    rsi_prev: str,
    rsi_curr: str,
    k_prev: str,
    d_prev: str,
    k_curr: str,
    d_curr: str,
) -> IndicatorSnapshot:
    now = datetime.now(tz=timezone.utc)
    return IndicatorSnapshot(
        evaluated_at=now,
        candle_open_utc=now,
        rsi_prev=Decimal(rsi_prev),
        rsi_curr=Decimal(rsi_curr),
        stoch_k_prev=Decimal(k_prev),
        stoch_d_prev=Decimal(d_prev),
        stoch_k_curr=Decimal(k_curr),
        stoch_d_curr=Decimal(d_curr),
    )


def test_signal_engine_long_signal() -> None:
    settings = Settings()
    engine = SignalEngine(settings)

    signal = engine.evaluate(
        _snapshot(rsi_prev="29", rsi_curr="31", k_prev="10", d_prev="12", k_curr="16", d_curr="14")
    )

    assert signal.signal_type == SignalType.LONG


def test_signal_engine_short_signal() -> None:
    settings = Settings()
    engine = SignalEngine(settings)

    signal = engine.evaluate(
        _snapshot(rsi_prev="72", rsi_curr="69", k_prev="90", d_prev="88", k_curr="85", d_curr="87")
    )

    assert signal.signal_type == SignalType.SHORT


def test_signal_engine_none() -> None:
    settings = Settings()
    engine = SignalEngine(settings)

    signal = engine.evaluate(
        _snapshot(rsi_prev="50", rsi_curr="51", k_prev="50", d_prev="50", k_curr="51", d_curr="50")
    )

    assert signal.signal_type == SignalType.NONE


def test_signal_engine_trend_filter_allows_long_on_daily_up() -> None:
    settings = Settings(taapi_interval="5m", strategy_trend_filter_enabled=True)
    engine = SignalEngine(settings)

    signal = engine.evaluate(
        _snapshot(rsi_prev="29", rsi_curr="31", k_prev="10", d_prev="12", k_curr="16", d_curr="14"),
        daily_trend="UP",
        interval="5m",
    )

    assert signal.signal_type == SignalType.LONG


def test_signal_engine_trend_filter_blocks_short_on_daily_up() -> None:
    settings = Settings(taapi_interval="5m", strategy_trend_filter_enabled=True)
    engine = SignalEngine(settings)

    signal = engine.evaluate(
        _snapshot(rsi_prev="72", rsi_curr="69", k_prev="90", d_prev="88", k_curr="85", d_curr="87"),
        daily_trend="UP",
        interval="5m",
    )

    assert signal.signal_type == SignalType.NONE
    assert "daily trend is UP" in signal.reason


def test_signal_engine_trend_filter_blocks_long_on_daily_down() -> None:
    settings = Settings(taapi_interval="5m", strategy_trend_filter_enabled=True)
    engine = SignalEngine(settings)

    signal = engine.evaluate(
        _snapshot(rsi_prev="29", rsi_curr="31", k_prev="10", d_prev="12", k_curr="16", d_curr="14"),
        daily_trend="DOWN",
        interval="5m",
    )

    assert signal.signal_type == SignalType.NONE
    assert "daily trend is DOWN" in signal.reason
