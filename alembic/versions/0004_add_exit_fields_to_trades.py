"""add exit fields to trades and ai suggestion columns

Revision ID: 0004_add_exit_fields_to_trades
Revises: 0003_add_openclaw_proposals
Create Date: 2026-02-20 00:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_add_exit_fields_to_trades"
down_revision = "0003_add_openclaw_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("price_entry", sa.Numeric(8, 4), nullable=True))
    op.add_column("trades", sa.Column("price_exit", sa.Numeric(8, 4), nullable=True))
    op.add_column("trades", sa.Column("exit_reason", sa.String(30), nullable=True))
    op.add_column("trades", sa.Column("exit_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("trades", sa.Column("exit_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("trades", sa.Column("hold_duration_secs", sa.Integer(), nullable=True))
    op.add_column("trades", sa.Column("exit_order_id", sa.String(120), nullable=True))

    op.add_column("ai_decisions", sa.Column("suggested_profit_target_cents", sa.Integer(), nullable=True))
    op.add_column("ai_decisions", sa.Column("suggested_stop_loss_cents", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_decisions", "suggested_stop_loss_cents")
    op.drop_column("ai_decisions", "suggested_profit_target_cents")

    op.drop_column("trades", "exit_order_id")
    op.drop_column("trades", "hold_duration_secs")
    op.drop_column("trades", "exit_confirmed_at")
    op.drop_column("trades", "exit_requested_at")
    op.drop_column("trades", "exit_reason")
    op.drop_column("trades", "price_exit")
    op.drop_column("trades", "price_entry")
