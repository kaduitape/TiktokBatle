"""character sprite sheet (animation frames in one image)

A character can now be uploaded as a sprite sheet -- one image holding the
poses in a grid -- instead of a single still. The grid is stored as
columns/rows so the admin describes it without measuring pixels.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Existing rows are still images: 0 columns keeps them rendering exactly as
# they do today, so the server_default is what makes this safe on a live table.
COLUMNS = (
    ("sprite_columns", "0"),
    ("sprite_rows", "1"),
    ("sprite_frame_count", "0"),
    ("sprite_fps", "10"),
)


def upgrade() -> None:
    for name, default in COLUMNS:
        op.add_column(
            "characters",
            sa.Column(name, sa.Integer(), nullable=False, server_default=default),
        )


def downgrade() -> None:
    for name, _ in COLUMNS:
        op.drop_column("characters", name)
