"""Add proposal flow tables and amendment columns.

Revision ID: 007
Revises: 006
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    # draft_share_tokens
    op.create_table(
        "draft_share_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # draft_comments
    op.create_table(
        "draft_comments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_name", sa.String(100), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # amendment_supports
    op.create_table(
        "amendment_supports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("signer_id", sa.Integer(), sa.ForeignKey("signatures.id"), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("amendment_id", "signer_id", name="uq_support_per_signer"),
    )

    # tier_challenges
    op.create_table(
        "tier_challenges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("challenger_id", sa.Integer(), sa.ForeignKey("signatures.id"), nullable=False),
        sa.Column("suggested_tier", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("amendment_id", "challenger_id", name="uq_challenge_per_signer"),
    )

    # content_reports
    op.create_table(
        "content_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("signatures.id"), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("amendment_id", "reporter_id", name="uq_report_per_signer"),
    )

    # admin_actions
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("via", sa.String(20), nullable=False),
        sa.Column("audit_response_id", sa.Integer(), nullable=True),
        sa.Column("acted_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # audit_responses
    op.create_table(
        "audit_responses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("model_name", sa.String(50), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=True),
        sa.Column("prompt_used", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("published", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("publication_decision_logged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("audited_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("amendment_id", "model_name", name="uq_audit_per_model"),
    )

    # Add columns to amendments
    op.add_column("amendments", sa.Column("author_id", sa.Integer(), nullable=True))
    op.add_column("amendments", sa.Column("title", sa.String(120), nullable=True))
    op.add_column("amendments", sa.Column("tier", sa.String(20), nullable=True))
    op.add_column("amendments", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.add_column("amendments", sa.Column("suggested_position", sa.Integer(), nullable=True))
    op.add_column("amendments", sa.Column("submission_language", sa.String(2), nullable=True))
    op.add_column("amendments", sa.Column("deletion_justification", sa.Text(), nullable=True))
    op.add_column("amendments", sa.Column("withdrawn_at", sa.DateTime(), nullable=True))
    op.add_column("amendments", sa.Column("deliberation_duration_days", sa.Integer(), nullable=True))
    op.add_column("amendments", sa.Column("tier_requalified", sa.Boolean(), server_default=sa.text("false")))
    op.add_column("amendments", sa.Column("tier_requalified_by", sa.String(20), nullable=True))
    op.add_column("amendments", sa.Column("tier_requalified_at", sa.DateTime(), nullable=True))
    op.add_column("amendments", sa.Column("tier_original", sa.String(20), nullable=True))


def downgrade():
    cols = [
        "author_id", "title", "tier", "expires_at", "suggested_position",
        "submission_language", "deletion_justification", "withdrawn_at",
        "deliberation_duration_days", "tier_requalified", "tier_requalified_by",
        "tier_requalified_at", "tier_original",
    ]
    for col in cols:
        op.drop_column("amendments", col)

    op.drop_table("audit_responses")
    op.drop_table("admin_actions")
    op.drop_table("content_reports")
    op.drop_table("tier_challenges")
    op.drop_table("amendment_supports")
    op.drop_table("draft_comments")
    op.drop_table("draft_share_tokens")
