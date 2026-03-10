"""A002 — rename principle_ids from Roman numerals to semantic names.

Also reorder: V (reciprocite) moves to position III.
No content changes — only identifiers.
Widens principle_id columns from VARCHAR(5) to VARCHAR(20) first.

Revision ID: 003
Revises: 002b
Create Date: 2026-03-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mapping: old Roman numeral -> new semantic id
MAPPING = {
    "I": "bienveillance",
    "II": "transparence",
    "III": "souverainete",
    "IV": "refus",
    "V": "reciprocite",
    "VI": "proactive",
    "VII": "agentique",
    "VIII": "deliberation",
}

REVERSE = {v: k for k, v in MAPPING.items()}


def upgrade() -> None:
    # First widen the principle_id column in comments (was VARCHAR(5))
    op.alter_column(
        "comments", "principle_id",
        type_=sa.String(20),
        existing_type=sa.String(5),
        existing_nullable=False,
    )

    # Rename principle_ids in comments table
    for old_id, new_id in MAPPING.items():
        op.execute(
            f"UPDATE comments SET principle_id = '{new_id}' WHERE principle_id = '{old_id}'"
        )

    # Rename principle_ids in amendments table (already VARCHAR(10) from 002b)
    for old_id, new_id in MAPPING.items():
        op.execute(
            f"UPDATE amendments SET principle_id = '{new_id}' WHERE principle_id = '{old_id}'"
        )


def downgrade() -> None:
    for new_id, old_id in REVERSE.items():
        op.execute(
            f"UPDATE comments SET principle_id = '{old_id}' WHERE principle_id = '{new_id}'"
        )
    for new_id, old_id in REVERSE.items():
        op.execute(
            f"UPDATE amendments SET principle_id = '{old_id}' WHERE principle_id = '{new_id}'"
        )

    op.alter_column(
        "comments", "principle_id",
        type_=sa.String(5),
        existing_type=sa.String(20),
        existing_nullable=False,
    )
