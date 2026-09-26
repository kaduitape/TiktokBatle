"""a sound effect per character movement

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Filled with an empty object right away: a NULL JSON column is what
    # once emptied the character list (see 0017), so none is left behind.
    for table in ("characters", "sprite_models"):
        op.add_column(table, sa.Column("sprite_sounds", sa.JSON(), nullable=True))
        op.execute(f"UPDATE {table} SET sprite_sounds = '{{}}' WHERE sprite_sounds IS NULL")


def downgrade() -> None:
    for table in ("sprite_models", "characters"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("sprite_sounds")
