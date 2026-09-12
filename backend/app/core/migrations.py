import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import settings

logger = logging.getLogger("migrations")

BACKEND_ROOT = Path(__file__).resolve().parents[2]
BASELINE_REVISION = "0001"


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.migration_database_url)
    return config


def run_migrations() -> None:
    """Brings the database up to head, adopting one that predates Alembic.

    Three cases, all handled without manual SQL:

    * Brand new database -> every migration runs in order.
    * Database already managed by Alembic -> only the missing ones run.
    * Database created by the old create_all() startup (so the tables exist
      but there is no alembic_version) -> it gets stamped at the baseline
      revision first, so the upgrade applies only the columns it's actually
      missing instead of trying to recreate existing tables.
    """
    engine = create_engine(settings.migration_database_url, poolclass=None)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    finally:
        engine.dispose()

    config = _alembic_config()

    if "alembic_version" not in tables and "battles" in tables:
        logger.warning(
            "database has tables but no alembic_version -- adopting it at revision %s "
            "before upgrading",
            BASELINE_REVISION,
        )
        command.stamp(config, BASELINE_REVISION)

    command.upgrade(config, "head")
    logger.info("database schema is up to date")
