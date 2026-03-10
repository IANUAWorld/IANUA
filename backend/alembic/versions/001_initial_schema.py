"""Initial schema — subscribers, comments, reactions

Revision ID: 001
Revises: None
Create Date: 2026-03-09
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Subscribers
    op.create_table(
        "subscribers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("lang", sa.String(5), server_default="fr"),
        sa.Column("token", sa.String(64), unique=True),
        sa.Column("confirmed", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("confirmed_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_subscribers_email", "subscribers", ["email"])

    # Comments
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("principle_id", sa.String(5), nullable=False),
        sa.Column("author_name", sa.String(100), nullable=False),
        sa.Column("author_country", sa.String(100), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("lang", sa.String(5), server_default="fr"),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("approved_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_comments_principle_id", "comments", ["principle_id"])
    op.create_index("ix_comments_status", "comments", ["status"])

    # Reactions
    op.create_table(
        "reactions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("comment_id", sa.Integer, sa.ForeignKey("comments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reaction_type", sa.String(20), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("comment_id", "reaction_type", "fingerprint", name="uq_reaction_per_fingerprint"),
    )


def downgrade() -> None:
    op.drop_table("reactions")
    op.drop_table("comments")
    op.drop_table("subscribers")
