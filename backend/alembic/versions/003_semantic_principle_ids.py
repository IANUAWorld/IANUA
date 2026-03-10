"""A002 — rename principle_ids from Roman numerals to semantic names.

Also reorder: V (reciprocite) moves to position III.
No content changes — only identifiers.

Revision ID: 003
Revises: 002b
Create Date: 2026-03-10
"""
from typing import Sequence, Union
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mapping: old Roman numeral → new semantic id
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
    # Rename principle_ids in comments table
    for old_id, new_id in MAPPING.items():
        op.execute(
            f"UPDATE comments SET principle_id = '{new_id}' WHERE principle_id = '{old_id}'"
        )

    # Rename principle_ids in amendments table
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
