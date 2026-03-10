"""Rebuild amendments tables — drop old schema, create comprehensive new one.

The old migration 002 created simple amendments + votes tables.
This migration drops them and rebuilds with the full governance schema.

Revision ID: 002b
Revises: 002
Create Date: 2026-03-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002b"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop old tables (empty, no data loss)
    op.drop_table("votes")
    op.drop_table("amendments")

    # ── Amendments (registre perenne) ──
    op.create_table(
        "amendments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(10), unique=True, nullable=False),

        # Cible
        sa.Column("principle_id", sa.String(10), nullable=True),
        sa.Column("target", sa.String(20), nullable=False),
        sa.Column("amendment_type", sa.String(20), nullable=False),

        # Contenu
        sa.Column("text_before", sa.Text, nullable=True),
        sa.Column("text_after", sa.Text, nullable=True),
        sa.Column("motivation", sa.Text, nullable=False),
        sa.Column("inspiration", sa.Text, nullable=True),

        # Voie de proposition
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("proposed_by", sa.String(100), nullable=True),
        sa.Column("supporting_comments", sa.ARRAY(sa.Integer), nullable=True),
        sa.Column("supporting_models", sa.ARRAY(sa.Text), nullable=True),

        # Gouvernance
        sa.Column("phase", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("ratified_by", sa.String(100), nullable=True),
        sa.Column("ratified_at", sa.DateTime, nullable=True),
        sa.Column("rejected_reason", sa.Text, nullable=True),

        # Votes (Phase 2+)
        sa.Column("votes_for", sa.Integer, server_default="0"),
        sa.Column("votes_against", sa.Integer, server_default="0"),
        sa.Column("votes_abstain", sa.Integer, server_default="0"),
        sa.Column("vote_threshold", sa.Integer, nullable=True),
        sa.Column("vote_opened_at", sa.DateTime, nullable=True),
        sa.Column("vote_closed_at", sa.DateTime, nullable=True),

        # Tracabilite
        sa.Column("proposed_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime, nullable=True),
        sa.Column("github_commit", sa.String(100), nullable=True),
        sa.Column("charte_version", sa.String(10), nullable=True),

        # Internationalisation
        sa.Column("motivation_en", sa.Text, nullable=True),
        sa.Column("motivation_es", sa.Text, nullable=True),
        sa.Column("text_after_en", sa.Text, nullable=True),
        sa.Column("text_after_es", sa.Text, nullable=True),
    )

    # ── Amendment Votes (Phase 2+) ──
    op.create_table(
        "amendment_votes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("amendment_id", sa.Integer, sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("voter_type", sa.String(10), nullable=False),
        sa.Column("voter_identity", sa.String(100), nullable=True),
        sa.Column("voter_model", sa.String(100), nullable=True),
        sa.Column("vote", sa.String(10), nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("voted_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("amendment_id", "voter_identity", name="uq_amendment_vote_per_voter"),
    )


def downgrade() -> None:
    op.drop_table("amendment_votes")
    op.drop_table("amendments")

    # Recreate old simple tables
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
