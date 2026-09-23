"""Noticing when the database is missing tables the code expects.

A half-applied migration is the worst kind of broken deploy: the app starts,
most of it works, and one feature answers "Internal Server Error" with no
explanation. It happened here -- a revision-number collision left a database
whose alembic_version claimed a revision that had never actually run -- and it
took a round trip through screenshots to find.

So the mismatch is reported instead of discovered: loudly in the log at
startup, and through /api/health, which anyone can open in a browser.
"""

from __future__ import annotations

import logging

from sqlalchemy import create_engine, inspect, text

from app.core.config import settings
from app.core.database import Base

# Importing the models is what fills Base.metadata. Without this the check
# silently compares against an empty set and reports a broken database as
# healthy -- which it did, the first time it was run on its own.
import app.models.models  # noqa: F401

logger = logging.getLogger("schema_check")


def inspect_schema() -> dict:
    """Which tables the models expect, which the database has, and the
    Alembic revision it claims to be at."""
    engine = create_engine(settings.migration_database_url, poolclass=None)
    try:
        inspector = inspect(engine)
        present = set(inspector.get_table_names())

        revision = None
        if "alembic_version" in present:
            with engine.connect() as connection:
                row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
                revision = row[0] if row else None
    finally:
        engine.dispose()

    expected = set(Base.metadata.tables)
    missing = sorted(expected - present)
    return {
        "revision": revision,
        "missing_tables": missing,
        "ok": not missing,
    }


def repair_missing_tables() -> dict:
    """Create tables the models declare but the database never got.

    Alembic cannot fix this on its own: it believes those revisions already
    ran, so it will never run them again. Creating the tables from the models
    is safe precisely because the revisions in question only ever created
    them -- there is no data to migrate and nothing to alter. Anything that
    needed more than a CREATE TABLE is left to Alembic and reported instead.
    """
    report = inspect_schema()
    missing = report["missing_tables"]
    if not missing:
        return report

    logger.error(
        "BANCO INCOMPLETO: faltam as tabelas %s. O alembic_version diz %s, mas essas "
        "migrations não chegaram a rodar -- normalmente porque duas revisões "
        "receberam o mesmo número. As telas que dependem delas respondem "
        "'Internal Server Error'.",
        ", ".join(missing),
        report["revision"],
    )

    engine = create_engine(settings.migration_database_url, poolclass=None)
    try:
        Base.metadata.create_all(
            engine, tables=[Base.metadata.tables[name] for name in missing]
        )
    except Exception:
        logger.exception("não consegui criar as tabelas que faltavam")
        return report
    finally:
        engine.dispose()

    logger.warning("tabelas criadas a partir dos modelos: %s", ", ".join(missing))
    return inspect_schema()


#: Kept as the old name so callers that only want the warning still work.
warn_if_incomplete = repair_missing_tables
