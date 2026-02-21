"""add openclaw proposals table

Revision ID: 0003_add_openclaw_proposals
Revises: 0002_add_ai_decisions
Create Date: 2026-02-20 00:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_add_openclaw_proposals"
down_revision = "0002_add_ai_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "openclaw_proposals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analysis_type", sa.String(50), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("proposal_text", sa.Text(), nullable=False),
        sa.Column("structured_change", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome_note", sa.Text(), nullable=True),
        sa.Column("evidence_window_days", sa.Integer(), nullable=False),
    )

    op.create_index("ix_openclaw_proposals_status", "openclaw_proposals", ["status"])
    op.create_index("ix_openclaw_proposals_proposed_at", "openclaw_proposals", ["proposed_at"])

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analyst_ro') THEN
                GRANT INSERT ON TABLE openclaw_proposals TO analyst_ro;
                GRANT USAGE, SELECT ON SEQUENCE openclaw_proposals_id_seq TO analyst_ro;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_openclaw_proposals_proposed_at", table_name="openclaw_proposals")
    op.drop_index("ix_openclaw_proposals_status", table_name="openclaw_proposals")
    op.drop_table("openclaw_proposals")
