"""tank war bosses get a 1.5M health pool

The mode shipped with the bosses on the generic default health pool, which the
viewers' armies tore through in a couple of gifts. Raising it is a data change,
so databases seeded before this need the same bump the seed now applies -- but
only when the value is still the old default, so an admin who tuned it by hand
keeps their number.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BOSS_HP = 1_500_000
OLD_DEFAULT = 100_000


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE characters SET xp_max = {BOSS_HP}
        WHERE xp_max <= {OLD_DEFAULT}
          AND id IN (
            SELECT side_a_character_id FROM battles WHERE mode = 'tank_war'
            UNION
            SELECT side_b_character_id FROM battles WHERE mode = 'tank_war'
          )
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE characters SET xp_max = {OLD_DEFAULT}
        WHERE xp_max = {BOSS_HP}
          AND id IN (
            SELECT side_a_character_id FROM battles WHERE mode = 'tank_war'
            UNION
            SELECT side_b_character_id FROM battles WHERE mode = 'tank_war'
          )
        """
    )
