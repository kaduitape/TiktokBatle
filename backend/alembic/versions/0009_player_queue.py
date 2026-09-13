"""players waiting for a slot on the field

The arena holds a fixed number of fighters; whoever arrives after that waits
here instead of pushing somebody else out. Existing rows default to False --
everyone already in a session is on the field.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column("queued", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("players", "queued")
