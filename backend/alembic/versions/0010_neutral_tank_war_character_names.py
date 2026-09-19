"""replace legacy political tank-war character names

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Restrict the update to the stock tank-war bosses, leaving characters in
    # other battle modes and any custom character names untouched.
    op.execute(
        sa.text(
            """
            UPDATE characters
            SET name = 'Time A'
            WHERE name = 'Lula'
              AND id IN (
                SELECT side_a_character_id FROM battles WHERE mode = 'tank_war'
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE characters
            SET name = 'Time B'
            WHERE name = 'Bolsonaro'
              AND id IN (
                SELECT side_b_character_id FROM battles WHERE mode = 'tank_war'
              )
            """
        )
    )


def downgrade() -> None:
    # This data correction is deliberately not reversed: restoring the legacy
    # political labels would be a surprising side effect of a schema rollback.
    pass
