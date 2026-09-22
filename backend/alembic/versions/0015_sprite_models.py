"""reusable animated character models

Saving a generated sheet apart from any one character: the art costs credits
and minutes to produce, so it should outlive the character it was first
applied to.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sprite_models",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("sprite_columns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sprite_rows", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sprite_frame_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sprite_fps", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("hit_image_url", sa.String(), nullable=True),
        sa.Column("fire_image_url", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("poses_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("sprite_models")
