"""fill in the clip list on rows that predate it

0016 added sprite_clips nullable with no default, so every character and
sprite model that already existed came out of it holding NULL. The API's
response model refuses None for a list, so building the response for *any*
one of those rows failed -- and the character list came back empty, with
nothing to create a character against either. The rows were never lost; the
answer could not be assembled.

Two halves to the repair, and both are needed: this fills in the rows, and
the schema now reads NULL as an empty list so a column added this way can
never empty a screen again.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# A JSON column holds text on SQLite and jsonb/json on Postgres; an empty
# array written as a literal string is read back correctly by both.
_EMPTY = "'[]'"


def upgrade() -> None:
    for table in ("characters", "sprite_models"):
        op.execute(
            f"UPDATE {table} SET sprite_clips = {_EMPTY} WHERE sprite_clips IS NULL"
        )


def downgrade() -> None:
    # Nothing to undo: an empty list and NULL mean the same thing here, and
    # putting the NULLs back would only recreate the failure.
    pass
