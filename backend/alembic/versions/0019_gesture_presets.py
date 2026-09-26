"""gestures the admin wrote, kept to be reused

A hand-written gesture used to live only in the generation form: it was spent
the moment the sheet came out, and using the same idea on the next character
meant typing every pose again. Saved here it becomes one more chip next to the
built-in ones.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gesture_presets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("poses_json", sa.JSON(), nullable=True),
        sa.Column("fps", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("lift", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # Declared inline rather than added afterwards: SQLite cannot ALTER a
        # unique constraint into an existing table.
        sa.UniqueConstraint("name", name="uq_gesture_presets_name"),
    )


def downgrade() -> None:
    op.drop_table("gesture_presets")
