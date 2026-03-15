"""Add human_voice and deadline_multiplier columns to amendments.

Revision ID: 009
Revises: 008
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("amendments", sa.Column("human_voice", sa.Text(), nullable=True))
    op.add_column("amendments", sa.Column("deadline_multiplier", sa.Float(), server_default="1.0", nullable=True))


def downgrade():
    op.drop_column("amendments", "deadline_multiplier")
    op.drop_column("amendments", "human_voice")
