"""Phase 2 — amendments and votes tables (structure only)

Revision ID: 002
Revises: 001
Create Date: 2026-03-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Amendments
    op.create_table(
        "amendments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("principle_id", sa.String(5), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), server_default="open"),
        sa.Column("threshold", sa.Integer, nullable=False),
        sa.Column("opens_at", sa.DateTime, nullable=False),
        sa.Column("closes_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # Votes
    op.create_table(
        "votes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("amendment_id", sa.Integer, sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vote_type", sa.String(20), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("lang", sa.String(5), server_default="fr"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("amendment_id", "fingerprint", name="uq_vote_per_fingerprint"),
    )


def downgrade() -> None:
    op.drop_table("votes")
    op.drop_table("amendments")
