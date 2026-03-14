"""Add audit_scope column to audit_responses.

Revision ID: 008
Revises: 007
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_responses",
        sa.Column("audit_scope", sa.String(20), server_default="amendment", nullable=True)
    )
    # Make amendment_id nullable for global audits
    op.alter_column("audit_responses", "amendment_id", nullable=True)


def downgrade():
    op.alter_column("audit_responses", "amendment_id", nullable=False)
    op.drop_column("audit_responses", "audit_scope")
