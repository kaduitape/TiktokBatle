"""Copy the live PostgreSQL application data into the versioned SQLite file.

Run once while the old PostgreSQL service is available. API keys are exported
to the ignored private settings file and deliberately omitted from SQLite.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

# Running ``python scripts/...`` makes the scripts directory the import root;
# add the backend root so the application package is available as ``app``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.database import Base, engine as destination_engine
from app.models import models  # noqa: F401 - registers all mapped tables


async def migrate() -> None:
    source_url = os.environ.get("SOURCE_DATABASE_URL", "").strip()
    if not source_url:
        raise SystemExit("SOURCE_DATABASE_URL is required")

    source_engine = create_async_engine(source_url)
    copied: list[tuple[str, int]] = []
    private_values: dict[str, str] = {}

    try:
        async with source_engine.connect() as source:
            async with destination_engine.begin() as destination:
                # This utility is repeatable: the destination always becomes
                # an exact snapshot instead of accumulating duplicated rows.
                for table in reversed(Base.metadata.sorted_tables):
                    await destination.execute(delete(table))

                for table in Base.metadata.sorted_tables:
                    rows = [dict(row) for row in (await source.execute(select(table))).mappings()]
                    if table.name == "app_secrets":
                        private_values = {
                            str(row["name"]): str(row["value"])
                            for row in rows
                            if row.get("name") and row.get("value")
                        }
                        continue
                    if rows:
                        await destination.execute(table.insert(), rows)
                    copied.append((table.name, len(rows)))

        if private_values:
            private_path = Path(settings.private_settings_file)
            private_path.parent.mkdir(parents=True, exist_ok=True)
            private_path.write_text(
                json.dumps(private_values, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            try:
                os.chmod(private_path, 0o600)
            except OSError:
                pass

        total = sum(count for _, count in copied)
        print(f"Copied {total} rows across {len(copied)} application tables.")
        print("Credentials were excluded from SQLite and exported privately.")
    finally:
        await source_engine.dispose()
        await destination_engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
