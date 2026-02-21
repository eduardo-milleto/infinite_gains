from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, JSON, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SignalModel(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candle_open_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    rsi_prev: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    rsi_curr: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    stoch_k_prev: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    stoch_d_prev: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    stoch_k_curr: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    stoch_d_curr: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    filter_result: Mapped[str | None] = mapped_column(String(128), nullable=True)
    market_slug: Mapped[str] = mapped_column(String(255), nullable=False)
    spread_at_eval: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False)

    trades: Mapped[list[TradeModel]] = relationship(back_populates="signal")
    ai_decisions: Mapped[list[AIDecisionModel]] = relationship(back_populates="signal")


class TradeModel(Base):
    __tablename__ = "trades"
    __table_args__ = (Index("ix_trades_status", "status"), Index("ix_trades_candle_open_utc", "candle_open_utc"))

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), nullable=False)
    market_slug: Mapped[str] = mapped_column(String(255), nullable=False)
    condition_id: Mapped[str] = mapped_column(String(255), nullable=False)
    token_id: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    candle_open_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    price_entry: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    price_exit: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    size_usdc: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    size_filled_usdc: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pnl_usdc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    fees_usdc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    exit_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hold_duration_secs: Mapped[int | None] = mapped_column(nullable=True)
    exit_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_order_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    raw_fill_event: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    signal: Mapped[SignalModel] = relationship(back_populates="trades")
    ai_decisions: Mapped[list[AIDecisionModel]] = relationship(back_populates="trade")


class ConfigHistoryModel(Base):
    __tablename__ = "config_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    config_section: Mapped[str] = mapped_column(String(64), nullable=False)
    param_key: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    proposal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")


class PerformanceMetricsModel(Base):
    __tablename__ = "performance_metrics"

    metric_date: Mapped[date] = mapped_column(Date, primary_key=True)
    total_trades: Mapped[int] = mapped_column(nullable=False)
    wins: Mapped[int] = mapped_column(nullable=False)
    losses: Mapped[int] = mapped_column(nullable=False)
    win_rate: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    gross_pnl_usdc: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    fees_usdc: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    net_pnl_usdc: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    max_drawdown_usdc: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    signals_generated: Mapped[int] = mapped_column(nullable=False)
    signals_filtered: Mapped[int] = mapped_column(nullable=False)
    avg_spread_at_entry: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    strategy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class MarketSessionModel(Base):
    __tablename__ = "market_sessions"

    candle_open_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    market_slug: Mapped[str] = mapped_column(String(255), nullable=False)
    condition_id: Mapped[str] = mapped_column(String(255), nullable=False)
    token_id_up: Mapped[str] = mapped_column(String(255), nullable=False)
    token_id_down: Mapped[str] = mapped_column(String(255), nullable=False)
    resolution_source: Mapped[str] = mapped_column(String(255), nullable=False)
    tick_size: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    market_end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)


class AIDecisionModel(Base):
    __tablename__ = "ai_decisions"
    __table_args__ = (
        Index("ix_ai_decisions_signal_id", "signal_id"),
        Index("ix_ai_decisions_trade_id", "trade_id"),
        Index("ix_ai_decisions_evaluated_at", "evaluated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), nullable=False)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    fallback_used: Mapped[bool] = mapped_column(nullable=False, default=False)
    latency_ms: Mapped[int] = mapped_column(nullable=False)
    raw_response_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    proceed: Mapped[bool] = mapped_column(nullable=False)
    direction_probability: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    market_price: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    edge: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    confidence: Mapped[int] = mapped_column(nullable=False)
    position_size_factor: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    warning_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    suggested_profit_target_cents: Mapped[int | None] = mapped_column(nullable=True)
    suggested_stop_loss_cents: Mapped[int | None] = mapped_column(nullable=True)
    outcome_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    outcome_settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    signal: Mapped[SignalModel] = relationship(back_populates="ai_decisions")
    trade: Mapped[TradeModel | None] = relationship(back_populates="ai_decisions")


class OpenClawProposalModel(Base):
    __tablename__ = "openclaw_proposals"
    __table_args__ = (
        Index("ix_openclaw_proposals_status", "status"),
        Index("ix_openclaw_proposals_proposed_at", "proposed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(50), nullable=False)
    findings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    proposal_text: Mapped[str] = mapped_column(Text, nullable=False)
    structured_change: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_window_days: Mapped[int] = mapped_column(nullable=False)
