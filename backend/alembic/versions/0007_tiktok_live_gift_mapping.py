"""add TikTok LIVE gift mapping and observed gift catalogue

The game-facing ``gift_key`` remains unchanged for the simulator and admin.
Real TikTok events are matched through the stable numeric ``tiktok_gift_id``
instead. Incoming, unmapped gifts are recorded for the live setup wizard.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("gifts", sa.Column("tiktok_gift_id", sa.String(), nullable=True))
    op.create_index("ix_gifts_tiktok_gift_id", "gifts", ["tiktok_gift_id"], unique=True)

    op.create_table(
        "tiktok_gift_observations",
        sa.Column("tiktok_gift_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("coins", sa.Integer(), nullable=True),
        sa.Column("seen_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tiktok_gift_observations")
    op.drop_index("ix_gifts_tiktok_gift_id", table_name="gifts")
    op.drop_column("gifts", "tiktok_gift_id")
