"""Add magic_tokens and vote_history tables.

Revision ID: 006
Revises: 005
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    # magic_tokens
    op.create_table(
        "magic_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False, index=True),
        sa.Column("token", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # vote_history
    op.create_table(
        "vote_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("vote_id", sa.Integer(), sa.ForeignKey("amendment_votes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("previous_vote", sa.String(10), nullable=False),
        sa.Column("previous_comment", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("vote_history")
    op.drop_table("magic_tokens")
