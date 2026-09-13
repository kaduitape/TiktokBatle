from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ComboTier, Gift


class GiftCache:
    """In-memory cache of Gift and ComboTier rows so the hot event-processing
    path never hits the DB per-gift. Admin CRUD endpoints call invalidate()
    after writes so nothing here is ever stale for more than one request."""

    def __init__(self) -> None:
        self._gifts: dict[str, Gift] = {}
        self._tiktok_gifts: dict[str, Gift] = {}
        self._combo_tiers: list[ComboTier] = []
        self._loaded = False

    async def ensure_loaded(self, db: AsyncSession) -> None:
        if not self._loaded:
            await self.refresh(db)

    async def refresh(self, db: AsyncSession) -> None:
        gifts = (await db.execute(select(Gift))).scalars().all()
        self._gifts = {g.gift_key: g for g in gifts}
        self._tiktok_gifts = {
            g.tiktok_gift_id: g for g in gifts if g.tiktok_gift_id
        }

        tiers = (await db.execute(select(ComboTier))).scalars().all()
        self._combo_tiers = sorted(tiers, key=lambda t: t.threshold)
        self._loaded = True

    def get(self, gift_key: str) -> Gift | None:
        return self._gifts.get(gift_key)

    def get_tiktok(self, tiktok_gift_id: str) -> Gift | None:
        """Resolve the ID emitted by TikTok, never an editable gift name."""
        return self._tiktok_gifts.get(str(tiktok_gift_id))

    def combo_tier_for(self, count: int) -> ComboTier | None:
        tier = None
        for t in self._combo_tiers:
            if count >= t.threshold:
                tier = t
            else:
                break
        return tier


gift_cache = GiftCache()
