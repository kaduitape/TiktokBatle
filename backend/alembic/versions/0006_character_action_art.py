"""character reaction art (taking damage, firing)

Two optional stills per character, swapped in for a moment when the character
takes a hit or fires. Null means the character has none, which is how every
existing row starts -- they keep rendering exactly as before.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("hit_image_url", "fire_image_url")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column("characters", sa.Column(name, sa.String(), nullable=True))


def downgrade() -> None:
    for name in COLUMNS:
        op.drop_column("characters", name)
