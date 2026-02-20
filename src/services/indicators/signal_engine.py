from __future__ import annotations

from src.config.settings import Settings
from src.core.enums import SignalType
from src.core.types import IndicatorSnapshot, Signal
from src.services.indicators.rsi import crossed_above, crossed_below
from src.services.indicators.stochastic import bearish_crossover, bullish_crossover


class SignalEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, snapshot: IndicatorSnapshot) -> Signal:
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
            return Signal(
                signal_type=SignalType.LONG,
                reason="RSI crossed above oversold and stochastic bullish crossover under oversold zone",
                indicator_snapshot=snapshot,
            )

        if short_signal:
            return Signal(
                signal_type=SignalType.SHORT,
                reason="RSI crossed below overbought and stochastic bearish crossover above overbought zone",
                indicator_snapshot=snapshot,
            )

        return Signal(
            signal_type=SignalType.NONE,
            reason="No crossover setup met",
            indicator_snapshot=snapshot,
        )
