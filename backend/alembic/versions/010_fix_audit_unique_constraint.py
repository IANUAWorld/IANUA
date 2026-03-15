"""Fix audit_responses unique constraint to include audit_scope.

Revision ID: 010
Revises: 009
"""
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_audit_per_model", "audit_responses", type_="unique")
    op.create_unique_constraint(
        "uq_audit_per_model_scope",
        "audit_responses",
        ["amendment_id", "model_name", "audit_scope"],
    )


def downgrade():
    op.drop_constraint("uq_audit_per_model_scope", "audit_responses", type_="unique")
    op.create_unique_constraint(
        "uq_audit_per_model",
        "audit_responses",
        ["amendment_id", "model_name"],
    )
