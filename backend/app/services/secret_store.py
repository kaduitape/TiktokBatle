"""Reading and writing credentials the admin pasted into the panel.

Stored in `app_secrets`, which no unauthenticated endpoint touches. Nothing
here ever returns a secret to a caller that only wants to display it -- use
`mask` for that.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.models import AppSecret

IMAGE_API_KEY = "image_api_key"


async def get(name: str) -> str | None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSecret, name)
        return (row.value or None) if row else None


async def set_value(db: AsyncSession, name: str, value: str) -> None:
    row = await db.get(AppSecret, name)
    if row:
        row.value = value
    else:
        db.add(AppSecret(name=name, value=value))
    await db.commit()


async def clear(db: AsyncSession, name: str) -> None:
    row = await db.get(AppSecret, name)
    if row:
        await db.delete(row)
        await db.commit()


def mask(value: str | None) -> str | None:
    """A preview that identifies which key is saved without revealing it."""
    if not value:
        return None
    tail = value[-4:] if len(value) > 4 else ""
    return f"{'•' * 6}{tail}"
