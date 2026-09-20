"""All database access for the captured gift catalogue.

Keeping the queries here means the catalogue service reasons about gifts
rather than about SQL, and the upsert that guards against duplicates lives in
exactly one place.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Gift, LiveGiftCatalogEntry


class GiftRepository:
    @staticmethod
    async def get(
        db: AsyncSession, platform: str, platform_gift_id: str
    ) -> LiveGiftCatalogEntry | None:
        return (
            await db.execute(
                select(LiveGiftCatalogEntry).where(
                    LiveGiftCatalogEntry.platform == platform,
                    LiveGiftCatalogEntry.platform_gift_id == str(platform_gift_id),
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_by_id(db: AsyncSession, entry_id: str) -> LiveGiftCatalogEntry | None:
        return await db.get(LiveGiftCatalogEntry, entry_id)

    @staticmethod
    async def list_all(db: AsyncSession) -> list[LiveGiftCatalogEntry]:
        return list(
            (
                await db.execute(
                    select(LiveGiftCatalogEntry).order_by(LiveGiftCatalogEntry.last_seen_at.desc())
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def rules_by_platform_id(db: AsyncSession) -> dict[tuple[str, str], Gift]:
        """The configured action for each catalogue entry, keyed the way the
        catalogue is keyed -- by platform and ID, never by name."""
        gifts = (
            (await db.execute(select(Gift).where(Gift.tiktok_gift_id.is_not(None))))
            .scalars()
            .all()
        )
        return {(gift.platform or "tiktok", str(gift.tiktok_gift_id)): gift for gift in gifts}

    @staticmethod
    async def count_unconfigured(db: AsyncSession) -> int:
        """Captured gifts that still have no rule attached."""
        configured = select(Gift.tiktok_gift_id).where(Gift.tiktok_gift_id.is_not(None))
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(LiveGiftCatalogEntry)
                    .where(
                        LiveGiftCatalogEntry.active.is_(True),
                        LiveGiftCatalogEntry.platform_gift_id.not_in(configured),
                    )
                )
            ).scalar_one()
        )


gift_repository = GiftRepository()
