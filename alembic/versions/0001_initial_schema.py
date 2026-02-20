"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-02-20 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candle_open_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rsi_prev", sa.Numeric(10, 4), nullable=False),
        sa.Column("rsi_curr", sa.Numeric(10, 4), nullable=False),
        sa.Column("stoch_k_prev", sa.Numeric(10, 4), nullable=False),
        sa.Column("stoch_d_prev", sa.Numeric(10, 4), nullable=False),
        sa.Column("stoch_k_curr", sa.Numeric(10, 4), nullable=False),
        sa.Column("stoch_d_curr", sa.Numeric(10, 4), nullable=False),
        sa.Column("signal_type", sa.String(16), nullable=False),
        sa.Column("filter_result", sa.String(128), nullable=True),
        sa.Column("market_slug", sa.String(255), nullable=False),
        sa.Column("spread_at_eval", sa.Numeric(10, 6), nullable=True),
        sa.Column("trading_mode", sa.String(16), nullable=False),
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("signal_id", sa.BigInteger(), sa.ForeignKey("signals.id"), nullable=False),
        sa.Column("market_slug", sa.String(255), nullable=False),
        sa.Column("condition_id", sa.String(255), nullable=False),
        sa.Column("token_id", sa.String(255), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("candle_open_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_id", sa.String(255), nullable=True),
        sa.Column("price", sa.Numeric(10, 6), nullable=False),
        sa.Column("size_usdc", sa.Numeric(18, 6), nullable=False),
        sa.Column("size_filled_usdc", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("resolved_direction", sa.String(16), nullable=True),
        sa.Column("pnl_usdc", sa.Numeric(18, 6), nullable=True),
        sa.Column("fees_usdc", sa.Numeric(18, 6), nullable=True),
        sa.Column("trading_mode", sa.String(16), nullable=False),
        sa.Column("raw_order_response", sa.JSON(), nullable=True),
        sa.Column("raw_fill_event", sa.JSON(), nullable=True),
    )

    op.create_table(
        "config_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("config_section", sa.String(64), nullable=False),
        sa.Column("param_key", sa.String(128), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.String(32), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.Column("proposal_id", sa.String(36), nullable=True),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
    )

    op.create_table(
        "performance_metrics",
        sa.Column("metric_date", sa.Date(), primary_key=True),
        sa.Column("total_trades", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Numeric(8, 4), nullable=False),
        sa.Column("gross_pnl_usdc", sa.Numeric(18, 6), nullable=False),
        sa.Column("fees_usdc", sa.Numeric(18, 6), nullable=False),
        sa.Column("net_pnl_usdc", sa.Numeric(18, 6), nullable=False),
        sa.Column("max_drawdown_usdc", sa.Numeric(18, 6), nullable=False),
        sa.Column("signals_generated", sa.Integer(), nullable=False),
        sa.Column("signals_filtered", sa.Integer(), nullable=False),
        sa.Column("avg_spread_at_entry", sa.Numeric(10, 6), nullable=True),
        sa.Column("strategy_snapshot", sa.JSON(), nullable=False),
        sa.Column("risk_snapshot", sa.JSON(), nullable=False),
    )

    op.create_table(
        "market_sessions",
        sa.Column("candle_open_utc", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("market_slug", sa.String(255), nullable=False),
        sa.Column("condition_id", sa.String(255), nullable=False),
        sa.Column("token_id_up", sa.String(255), nullable=False),
        sa.Column("token_id_down", sa.String(255), nullable=False),
        sa.Column("resolution_source", sa.String(255), nullable=False),
        sa.Column("tick_size", sa.Numeric(10, 6), nullable=False),
        sa.Column("market_end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_outcome", sa.String(16), nullable=True),
    )

    op.create_index("ix_trades_status", "trades", ["status"])
    op.create_index("ix_trades_candle_open_utc", "trades", ["candle_open_utc"])
    op.create_index("ix_signals_candle_open_utc", "signals", ["candle_open_utc"])


def downgrade() -> None:
    op.drop_index("ix_signals_candle_open_utc", table_name="signals")
    op.drop_index("ix_trades_candle_open_utc", table_name="trades")
    op.drop_index("ix_trades_status", table_name="trades")
    op.drop_table("market_sessions")
    op.drop_table("performance_metrics")
    op.drop_table("config_history")
    op.drop_table("trades")
    op.drop_table("signals")
