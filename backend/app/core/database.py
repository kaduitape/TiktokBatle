from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine_options = {"echo": False, "future": True}
if settings.database_url.startswith("sqlite"):
    engine_options["connect_args"] = {"timeout": 30, "check_same_thread": False}

engine = create_async_engine(settings.database_url, **engine_options)


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        # DELETE keeps the complete persistent state in one Git-tracked file;
        # WAL would put recent writes in an easy-to-forget sidecar.
        cursor.execute("PRAGMA journal_mode=DELETE")
        cursor.close()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
