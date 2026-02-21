from __future__ import annotations

from enum import StrEnum


class TradeDirection(StrEnum):
    UP = "UP"
    DOWN = "DOWN"


class SignalType(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    MATCHED = "MATCHED"
    CONFIRMED = "CONFIRMED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TradingMode(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class ConfigChangedBy(StrEnum):
    SYSTEM_LEARNING = "SYSTEM_LEARNING"
    HUMAN_TELEGRAM = "HUMAN_TELEGRAM"
    STARTUP = "STARTUP"


class ProposalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AIFallbackMode(StrEnum):
    VETO = "VETO"
    PROCEED = "PROCEED"
    TELEGRAM = "TELEGRAM"


class ExitMode(StrEnum):
    SCALP = "SCALP"
    HOLD = "HOLD"


class ExitReason(StrEnum):
    PROFIT_TARGET = "PROFIT_TARGET"
    STOP_LOSS = "STOP_LOSS"
    TIME_EXIT = "TIME_EXIT"
    SIGNAL_REVERSAL = "SIGNAL_REVERSAL"
    RESOLUTION = "RESOLUTION"


class OpenClawProposalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
