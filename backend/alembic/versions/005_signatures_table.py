"""Create signatures table — global support for the Ianua initiative.

Revision ID: 005
Revises: 004
Create Date: 2026-03-11
"""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signatures",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("pseudo", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("lang", sa.String(5), server_default="fr"),
        sa.Column("token", sa.String(64), unique=True),
        sa.Column("confirmed", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("confirmed_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("signatures")
