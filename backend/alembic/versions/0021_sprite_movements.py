"""one sprite sheet per character movement

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfilled at once: a NULL JSON list is what emptied the character list
    # once (0017).
    for table in ("characters", "sprite_models"):
        op.add_column(table, sa.Column("sprite_movements", sa.JSON(), nullable=True))
        op.execute(f"UPDATE {table} SET sprite_movements = '[]' WHERE sprite_movements IS NULL")


def downgrade() -> None:
    for table in ("sprite_models", "characters"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("sprite_movements")
