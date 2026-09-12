"""team PvP mode columns

Adds the battle mode selector and the per-fighter combat stats used by the
"team_pvp" mode. Every column carries a server_default so it can be added to
a table that already has rows -- without one, a NOT NULL column can't be
added to an existing database.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "battles",
        sa.Column("mode", sa.String(), nullable=False, server_default="character"),
    )

    op.add_column("players", sa.Column("power", sa.Float(), nullable=False, server_default="0"))
    op.add_column("players", sa.Column("peak_power", sa.Float(), nullable=False, server_default="0"))
    op.add_column("players", sa.Column("level", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("players", sa.Column("kills", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "players",
        sa.Column("eliminated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("players", "eliminated")
    op.drop_column("players", "kills")
    op.drop_column("players", "level")
    op.drop_column("players", "peak_power")
    op.drop_column("players", "power")
    op.drop_column("battles", "mode")
