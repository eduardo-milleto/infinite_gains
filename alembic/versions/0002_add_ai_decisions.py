"""add ai_decisions table

Revision ID: 0002_add_ai_decisions
Revises: 0001_initial_schema
Create Date: 2026-02-20 00:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_add_ai_decisions"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_decisions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("signal_id", sa.BigInteger(), sa.ForeignKey("signals.id"), nullable=False),
        sa.Column("trade_id", sa.BigInteger(), sa.ForeignKey("trades.id"), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("raw_response_hash", sa.String(64), nullable=False),
        sa.Column("proceed", sa.Boolean(), nullable=False),
        sa.Column("direction_probability", sa.Numeric(10, 6), nullable=False),
        sa.Column("market_price", sa.Numeric(10, 6), nullable=False),
        sa.Column("edge", sa.Numeric(10, 6), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("position_size_factor", sa.Numeric(10, 6), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("warning_flags", sa.JSON(), nullable=False),
        sa.Column("outcome_pnl", sa.Numeric(18, 6), nullable=True),
        sa.Column("outcome_settled_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_ai_decisions_signal_id", "ai_decisions", ["signal_id"])
    op.create_index("ix_ai_decisions_trade_id", "ai_decisions", ["trade_id"])
    op.create_index("ix_ai_decisions_evaluated_at", "ai_decisions", ["evaluated_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_decisions_evaluated_at", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_trade_id", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_signal_id", table_name="ai_decisions")
    op.drop_table("ai_decisions")
