"""automatic gift catalogue captured from the LIVE

Replaces the narrow tiktok_gift_observations table with live_gifts, which
records artwork, value and free-form provider metadata alongside the ID and
is keyed by (platform, platform_gift_id) so a second platform can be added
without another table. Existing observations are carried over so nothing
already discovered is lost.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-19
"""
from datetime import datetime
from typing import Any, Sequence, Union
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "live_gifts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("platform", sa.String(), nullable=False, server_default="tiktok"),
        sa.Column("platform_gift_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("cached_image_url", sa.String(), nullable=True),
        sa.Column("diamond_value", sa.Integer(), nullable=True),
        sa.Column("coin_value", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("times_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # Declared inline rather than added afterwards: SQLite cannot ALTER a
        # constraint into an existing table, and the dev/test database is
        # SQLite even though production is Postgres.
        sa.UniqueConstraint("platform", "platform_gift_id", name="uq_live_gifts_platform_id"),
    )

    # A gift rule belongs to the platform whose ID it carries. Everything that
    # existed before this came from TikTok.
    op.add_column("gifts", sa.Column("platform", sa.String(), nullable=False, server_default="tiktok"))

    _carry_over_observations()
    op.drop_table("tiktok_gift_observations")


def _carry_over_observations() -> None:
    """Move whatever the old wizard had already discovered into the catalogue."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tiktok_gift_observations" not in inspector.get_table_names():
        return

    rows = bind.execute(
        sa.text(
            "SELECT tiktok_gift_id, name, coins, seen_count, first_seen_at, last_seen_at "
            "FROM tiktok_gift_observations"
        )
    ).fetchall()
    if not rows:
        return

    live_gifts = sa.table(
        "live_gifts",
        sa.column("id", sa.String),
        sa.column("platform", sa.String),
        sa.column("platform_gift_id", sa.String),
        sa.column("name", sa.String),
        sa.column("diamond_value", sa.Integer),
        sa.column("coin_value", sa.Integer),
        sa.column("times_received", sa.Integer),
        sa.column("first_seen_at", sa.DateTime(timezone=True)),
        sa.column("last_seen_at", sa.DateTime(timezone=True)),
        sa.column("active", sa.Boolean),
        sa.column("metadata_json", sa.JSON),
    )
    op.bulk_insert(
        live_gifts,
        [
            {
                "id": uuid.uuid4().hex,
                "platform": "tiktok",
                "platform_gift_id": str(row[0]),
                "name": row[1],
                # The old table called it "coins" but stored TikTok's diamond
                # count, which is the same number under both names.
                "diamond_value": row[2],
                "coin_value": row[2],
                "times_received": row[3] or 0,
                "first_seen_at": _as_datetime(row[4]),
                "last_seen_at": _as_datetime(row[5]),
                "active": True,
                "metadata_json": {"imported_from": "tiktok_gift_observations"},
            }
            for row in rows
        ],
    )


def _as_datetime(value: Any) -> datetime | None:
    """SQLite hands timestamps back as strings, Postgres as datetimes.

    The bulk insert binds a DateTime column, which accepts only the latter, so
    normalise here rather than assuming whichever database the operator runs.
    """
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:26] if "." in text else text, fmt)
        except ValueError:
            continue
    return None


def downgrade() -> None:
    op.create_table(
        "tiktok_gift_observations",
        sa.Column("tiktok_gift_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("coins", sa.Integer(), nullable=True),
        sa.Column("seen_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    with op.batch_alter_table("gifts") as batch:
        batch.drop_column("platform")
    # The unique constraint was created inline, so it goes with the table.
    op.drop_table("live_gifts")
