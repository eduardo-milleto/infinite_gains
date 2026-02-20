from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core.enums import OrderStatus, SignalType, TradeDirection, TradingMode


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
