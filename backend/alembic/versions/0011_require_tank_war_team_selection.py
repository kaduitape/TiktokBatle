"""require an A/B chat selection before entering tank war

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing players start as unselected. This keeps any legacy ball created
    # by a gift out of Eleições 2026 until that viewer explicitly comments A or
    # B, while preserving the historical row and its event totals.
    op.add_column(
        "players",
        sa.Column("team_selected", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("players", "team_selected")
