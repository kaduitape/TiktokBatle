"""named clips inside a character's sprite sheet

A single looping row repeats the same frames at the same rate forever, which
reads as a machine. Clips let the base row loop while the other rows are
gestures played occasionally, so the character looks alive between actions.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable with no default: an existing character keeps its single loop
    # until somebody describes clips for it. Saved sprite models carry the same
    # list, so applying one brings its gestures along.
    op.add_column("characters", sa.Column("sprite_clips", sa.JSON(), nullable=True))
    op.add_column("sprite_models", sa.Column("sprite_clips", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sprite_models") as batch:
        batch.drop_column("sprite_clips")
    with op.batch_alter_table("characters") as batch:
        batch.drop_column("sprite_clips")
