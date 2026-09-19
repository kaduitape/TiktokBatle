"""gifts selected per battle

Empty for a battle means every active gift, so existing battles are unaffected.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "battle_gifts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("battle_id", sa.String(), sa.ForeignKey("battles.id"), nullable=False),
        sa.Column("gift_id", sa.String(), sa.ForeignKey("gifts.id"), nullable=False),
    )
    op.create_index("ix_battle_gifts_battle_id", "battle_gifts", ["battle_id"])


def downgrade() -> None:
    op.drop_index("ix_battle_gifts_battle_id", table_name="battle_gifts")
    op.drop_table("battle_gifts")
