from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.config.settings import Settings
from src.core.enums import ExitReason
from src.core.types import AIDecision, ExitDecision, ExitParameters
from src.db.models import TradeModel


class ExitEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def resolve_exit_parameters(self, ai_decision: AIDecision | None) -> ExitParameters:
        suggested_profit = ai_decision.suggested_profit_target_cents if ai_decision is not None else None
        suggested_stop = ai_decision.suggested_stop_loss_cents if ai_decision is not None else None

        profit_target = self._settings.exit_profit_target_cents
        stop_loss = self._settings.exit_stop_loss_cents

        if suggested_profit is not None:
            profit_target = self._clamp_int(
                suggested_profit,
                self._settings.exit_min_profit_cents,
                self._settings.exit_max_profit_cents,
            )

        if suggested_stop is not None:
            stop_loss = self._clamp_int(
                suggested_stop,
                self._settings.exit_min_stop_cents,
                self._settings.exit_max_stop_cents,
            )

        return ExitParameters(
            profit_target_cents=profit_target,
            stop_loss_cents=stop_loss,
            time_before_close_secs=self._settings.exit_time_before_close_secs,
            exit_on_signal_reversal=self._settings.exit_on_signal_reversal,
        )

    def evaluate(
        self,
        *,
        trade: TradeModel,
        current_price: Decimal,
        market_end_time: datetime,
        now_utc: datetime,
        exit_parameters: ExitParameters,
        reversal_detected: bool,
    ) -> ExitDecision:
        entry_price = Decimal(str(trade.price_entry or trade.price))
        size_usdc = Decimal(str(trade.size_usdc))
        shares = Decimal("0")
        if entry_price > 0:
            shares = size_usdc / entry_price

        pnl = (current_price - entry_price) * shares
        hold_duration_secs = int((now_utc - trade.candle_open_utc).total_seconds())

        target_price = entry_price + (Decimal(exit_parameters.profit_target_cents) / Decimal("100"))
        stop_price = entry_price - (Decimal(exit_parameters.stop_loss_cents) / Decimal("100"))

        if current_price >= target_price:
            return ExitDecision(
                should_exit=True,
                reason=ExitReason.PROFIT_TARGET,
                current_price=current_price,
                pnl_usdc=pnl,
                hold_duration_secs=hold_duration_secs,
            )

        if current_price <= stop_price:
            return ExitDecision(
                should_exit=True,
                reason=ExitReason.STOP_LOSS,
                current_price=current_price,
                pnl_usdc=pnl,
                hold_duration_secs=hold_duration_secs,
            )

        secs_to_close = int((market_end_time - now_utc).total_seconds())
        if secs_to_close <= exit_parameters.time_before_close_secs:
            return ExitDecision(
                should_exit=True,
                reason=ExitReason.TIME_EXIT,
                current_price=current_price,
                pnl_usdc=pnl,
                hold_duration_secs=hold_duration_secs,
            )

        if exit_parameters.exit_on_signal_reversal and reversal_detected:
            return ExitDecision(
                should_exit=True,
                reason=ExitReason.SIGNAL_REVERSAL,
                current_price=current_price,
                pnl_usdc=pnl,
                hold_duration_secs=hold_duration_secs,
            )

        return ExitDecision(
            should_exit=False,
            reason=None,
            current_price=current_price,
            pnl_usdc=pnl,
            hold_duration_secs=hold_duration_secs,
        )

    @staticmethod
    def _clamp_int(value: int, lower: int, upper: int) -> int:
        if value < lower:
            return lower
        if value > upper:
            return upper
        return value
