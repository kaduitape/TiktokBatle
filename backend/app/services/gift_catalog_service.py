"""The catalogue itself: one row per gift the LIVE has ever sent.

``register_or_update`` is the only way a gift enters it, and it is written to
be safe to call on every single gift event of a busy stream: a gift already
known is updated in place, never inserted twice, and fields the provider left
out do not overwrite what an earlier event did report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import LiveGiftCatalogEntry
from app.services.gift_image_cache import gift_image_cache
from app.services.gift_normalizer import CapturedGift
from app.services.gift_repository import gift_repository

logger = logging.getLogger("gift_catalog")


@dataclass
class CatalogResult:
    entry: LiveGiftCatalogEntry
    is_new: bool
    #: True when an already-known gift gained information it did not have.
    was_enriched: bool = False


class GiftCatalogService:
    async def register_or_update(
        self, db: AsyncSession, captured: CapturedGift, *, count_receipt: bool = True
    ) -> CatalogResult:
        entry = await gift_repository.get(db, captured.platform, captured.platform_gift_id)

        if entry is None:
            entry = LiveGiftCatalogEntry(
                platform=captured.platform,
                platform_gift_id=captured.platform_gift_id,
                name=captured.name,
                image_url=captured.image_url,
                diamond_value=captured.diamond_value,
                coin_value=captured.coin_value,
                times_received=captured.quantity if count_receipt else 0,
                metadata_json=dict(captured.metadata),
                active=True,
            )
            try:
                # A savepoint, so losing this race rolls back only the failed
                # INSERT. A plain flush would poison the pipeline's whole
                # transaction, taking the XP change and the battle event with it.
                async with db.begin_nested():
                    db.add(entry)
                    await db.flush()
            except IntegrityError:
                # Two events for an unknown gift can race into the same insert.
                # The unique index is what makes that a recoverable collision
                # rather than a duplicate row.
                existing = await gift_repository.get(
                    db, captured.platform, captured.platform_gift_id
                )
                if existing is None:
                    raise
                return await self._update(db, existing, captured, count_receipt)
            return CatalogResult(entry=entry, is_new=True)

        return await self._update(db, entry, captured, count_receipt)

    async def _update(
        self,
        db: AsyncSession,
        entry: LiveGiftCatalogEntry,
        captured: CapturedGift,
        count_receipt: bool,
    ) -> CatalogResult:
        enriched = False

        # Only ever fill in or correct with something the provider actually
        # sent. A later event that omits the name must not erase it.
        if captured.name and captured.name != entry.name:
            entry.name = captured.name
            enriched = True
        if captured.image_url and captured.image_url != entry.image_url:
            entry.image_url = captured.image_url
            enriched = True
        if captured.diamond_value is not None and captured.diamond_value != entry.diamond_value:
            entry.diamond_value = captured.diamond_value
            enriched = True
        if captured.coin_value is not None and captured.coin_value != entry.coin_value:
            entry.coin_value = captured.coin_value
            enriched = True
        if captured.metadata:
            merged = {**(entry.metadata_json or {}), **captured.metadata}
            if merged != (entry.metadata_json or {}):
                entry.metadata_json = merged
                enriched = True

        if count_receipt:
            entry.times_received = (entry.times_received or 0) + max(1, captured.quantity)
        entry.last_seen_at = datetime.now(timezone.utc)
        await db.flush()
        return CatalogResult(entry=entry, is_new=False, was_enriched=enriched)

    async def cache_artwork(
        self, db: AsyncSession, entry: LiveGiftCatalogEntry
    ) -> str | None:
        """Copy the gift's icon locally so the game stops depending on the CDN."""
        if entry.cached_image_url:
            return entry.cached_image_url
        cached = await gift_image_cache.ensure(
            entry.platform, entry.platform_gift_id, entry.image_url
        )
        if cached:
            entry.cached_image_url = cached
            await db.flush()
        return cached

    @staticmethod
    def display_image(entry: LiveGiftCatalogEntry) -> str | None:
        """Prefer the local copy; fall back to the CDN; then to nothing at all
        so the panel can draw its placeholder."""
        return entry.cached_image_url or entry.image_url


gift_catalog_service = GiftCatalogService()
