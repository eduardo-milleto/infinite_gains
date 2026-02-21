from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core.enums import ExitReason, OrderStatus, SignalType, TradeDirection, TradingMode


@dataclass(frozen=True, slots=True)
class IndicatorSnapshot:
    evaluated_at: datetime
    candle_open_utc: datetime
    rsi_prev: Decimal
    rsi_curr: Decimal
    stoch_k_prev: Decimal
    stoch_d_prev: Decimal
    stoch_k_curr: Decimal
    stoch_d_curr: Decimal


@dataclass(frozen=True, slots=True)
class Signal:
    signal_type: SignalType
    reason: str
    indicator_snapshot: IndicatorSnapshot

    @property
    def direction(self) -> TradeDirection | None:
        if self.signal_type == SignalType.LONG:
            return TradeDirection.UP
        if self.signal_type == SignalType.SHORT:
            return TradeDirection.DOWN
        return None


@dataclass(frozen=True, slots=True)
class MarketContext:
    market_slug: str
    condition_id: str
    token_id_up: str
    token_id_down: str
    spread: Decimal
    tick_size: Decimal
    market_end_time: datetime
    resolution_source: str
    up_price: Decimal = Decimal("0.50")
    down_price: Decimal = Decimal("0.50")


@dataclass(frozen=True, slots=True)
class OrderResult:
    order_id: str | None
    status: OrderStatus
    direction: TradeDirection
    token_id: str
    price: Decimal
    size_usdc: Decimal
    size_filled_usdc: Decimal = Decimal("0")
    failure_reason: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ApprovalProposal:
    proposal_id: str
    section: str
    param_key: str
    old_value: str | None
    new_value: str
    justification: str
    changed_by: str
    trading_mode: TradingMode


@dataclass(frozen=True, slots=True)
class CandlePoint:
    open_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    direction: str
    pct_change: Decimal


@dataclass(frozen=True, slots=True)
class IndicatorPoint:
    candle_open_utc: datetime
    rsi: Decimal
    stoch_k: Decimal
    stoch_d: Decimal


@dataclass(frozen=True, slots=True)
class OrderBookSnapshot:
    up_price: Decimal
    down_price: Decimal
    spread: Decimal
    depth_up: Decimal
    depth_down: Decimal


@dataclass(frozen=True, slots=True)
class RecentBotPerformance:
    win_rate: Decimal
    net_pnl_usdc: Decimal
    total_trades: int
    ai_veto_rate: Decimal
    ai_total_decisions: int


@dataclass(frozen=True, slots=True)
class AITradingContext:
    signal_id: int
    signal_type: SignalType
    signal_reason: str
    candle_open_utc: datetime
    market_slug: str
    market_end_time: datetime
    orderbook: OrderBookSnapshot
    target_market_price: Decimal
    candle_history: tuple[CandlePoint, ...]
    indicator_history: tuple[IndicatorPoint, ...]
    performance_7d: RecentBotPerformance
    hour_of_day_utc: int
    day_of_week_utc: str


@dataclass(frozen=True, slots=True)
class AIDecision:
    proceed: bool
    direction_probability: Decimal
    market_price: Decimal
    edge: Decimal
    confidence: int
    position_size_factor: Decimal
    reasoning: str
    warning_flags: tuple[str, ...]
    suggested_profit_target_cents: int | None = None
    suggested_stop_loss_cents: int | None = None
    fallback_used: bool = False


@dataclass(frozen=True, slots=True)
class ExitParameters:
    profit_target_cents: int
    stop_loss_cents: int
    time_before_close_secs: int
    exit_on_signal_reversal: bool


@dataclass(frozen=True, slots=True)
class ExitDecision:
    should_exit: bool
    reason: ExitReason | None
    current_price: Decimal
    pnl_usdc: Decimal
    hold_duration_secs: int
