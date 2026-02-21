from __future__ import annotations

from src.config.settings import Settings
from src.core.enums import SignalType
from src.core.types import IndicatorSnapshot, Signal
from src.services.indicators.rsi import crossed_above, crossed_below
from src.services.indicators.stochastic import bearish_crossover, bullish_crossover


class SignalEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(
        self,
        snapshot: IndicatorSnapshot,
        *,
        daily_trend: str | None = None,
        interval: str | None = None,
    ) -> Signal:
        long_signal = (
            crossed_above(
                self._settings.strategy_rsi_oversold,
                snapshot.rsi_prev,
                snapshot.rsi_curr,
            )
            and bullish_crossover(
                snapshot.stoch_k_prev,
                snapshot.stoch_d_prev,
                snapshot.stoch_k_curr,
                snapshot.stoch_d_curr,
            )
            and snapshot.stoch_k_curr < self._settings.strategy_stoch_oversold
            and snapshot.stoch_d_curr < self._settings.strategy_stoch_oversold
        )

        short_signal = (
            crossed_below(
                self._settings.strategy_rsi_overbought,
                snapshot.rsi_prev,
                snapshot.rsi_curr,
            )
            and bearish_crossover(
                snapshot.stoch_k_prev,
                snapshot.stoch_d_prev,
                snapshot.stoch_k_curr,
                snapshot.stoch_d_curr,
            )
            and snapshot.stoch_k_curr > self._settings.strategy_stoch_overbought
            and snapshot.stoch_d_curr > self._settings.strategy_stoch_overbought
        )

        if long_signal:
            base_signal = Signal(
                signal_type=SignalType.LONG,
                reason="RSI crossed above oversold and stochastic bullish crossover under oversold zone",
                indicator_snapshot=snapshot,
            )
            return self._apply_trend_filter(base_signal, daily_trend=daily_trend, interval=interval)

        if short_signal:
            base_signal = Signal(
                signal_type=SignalType.SHORT,
                reason="RSI crossed below overbought and stochastic bearish crossover above overbought zone",
                indicator_snapshot=snapshot,
            )
            return self._apply_trend_filter(base_signal, daily_trend=daily_trend, interval=interval)

        return Signal(
            signal_type=SignalType.NONE,
            reason="No crossover setup met",
            indicator_snapshot=snapshot,
        )

    def _apply_trend_filter(
        self,
        signal: Signal,
        *,
        daily_trend: str | None,
        interval: str | None,
    ) -> Signal:
        if signal.signal_type == SignalType.NONE:
            return signal
        if not self._settings.strategy_trend_filter_enabled:
            return signal

        current_interval = (interval or self._settings.taapi_interval).lower()
        if current_interval != "5m":
            return signal

        trend = (daily_trend or "").upper()
        if trend == "UP" and signal.signal_type == SignalType.LONG:
            return signal
        if trend == "DOWN" and signal.signal_type == SignalType.SHORT:
            return signal

        if trend == "UP":
            reason = "Trend filter veto: daily trend is UP, only LONG pullbacks are allowed on 5m"
        elif trend == "DOWN":
            reason = "Trend filter veto: daily trend is DOWN, only SHORT pullbacks are allowed on 5m"
        else:
            reason = "Trend filter veto: daily trend is FLAT/unknown, skipping 5m entries"

        return Signal(
            signal_type=SignalType.NONE,
            reason=reason,
            indicator_snapshot=signal.indicator_snapshot,
        )
