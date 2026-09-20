from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.core.database import get_db
from app.models.models import ComboTier, Gift
from app.schemas.schemas import ComboTierIn, ComboTierOut, GiftIn, GiftOut
from app.services.gift_cache import gift_cache
from app.services.gift_repository import gift_repository

router = APIRouter(prefix="/api/gifts", tags=["gifts"])
combo_router = APIRouter(prefix="/api/combo-tiers", tags=["combo-tiers"])


@router.get("", response_model=list[GiftOut])
async def list_gifts(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Gift))).scalars().all()


@router.get("/tiktok-observations")
async def list_tiktok_gift_observations(
    db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    """Gifts received from a real LIVE, including ones not mapped yet.

    Kept in the shape the live setup wizard reads. The data now comes from the
    automatic catalogue (live_gifts), which records the same gifts with more
    detail -- see /api/live-gifts for the full view.
    """
    entries = await gift_repository.list_all(db)
    rules = await gift_repository.rules_by_platform_id(db)
    out = []
    for entry in entries:
        rule = rules.get((entry.platform, entry.platform_gift_id))
        out.append(
            {
                "tiktok_gift_id": entry.platform_gift_id,
                "name": entry.name or entry.platform_gift_id,
                "coins": entry.diamond_value,
                "seen_count": entry.times_received,
                "first_seen_at": entry.first_seen_at,
                "last_seen_at": entry.last_seen_at,
                "configured_gift_id": rule.id if rule else None,
                "configured_gift_key": rule.gift_key if rule else None,
            }
        )
    return out


@router.post("", response_model=GiftOut)
async def create_gift(body: GiftIn, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    existing = (
        await db.execute(select(Gift).where(Gift.gift_key == body.gift_key))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "gift_key already exists")
    await _validate_tiktok_gift_id(db, body.tiktok_gift_id)
    gift = Gift(**body.model_dump())
    db.add(gift)
    await db.commit()
    await db.refresh(gift)
    await gift_cache.refresh(db)
    return gift


@router.put("/{gift_id}", response_model=GiftOut)
async def update_gift(
    gift_id: str, body: GiftIn, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    gift = await db.get(Gift, gift_id)
    if not gift:
        raise HTTPException(404, "gift not found")
    await _validate_tiktok_gift_id(db, body.tiktok_gift_id, excluding_gift_id=gift_id)
    for k, v in body.model_dump().items():
        setattr(gift, k, v)
    await db.commit()
    await db.refresh(gift)
    await gift_cache.refresh(db)
    return gift


@router.delete("/{gift_id}")
async def delete_gift(gift_id: str, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    gift = await db.get(Gift, gift_id)
    if not gift:
        raise HTTPException(404, "gift not found")
    await db.delete(gift)
    await db.commit()
    await gift_cache.refresh(db)
    return {"ok": True}


async def _validate_tiktok_gift_id(
    db: AsyncSession, tiktok_gift_id: str | None, excluding_gift_id: str | None = None
) -> None:
    if not tiktok_gift_id:
        return
    existing = (
        await db.execute(select(Gift).where(Gift.tiktok_gift_id == tiktok_gift_id))
    ).scalar_one_or_none()
    if existing and existing.id != excluding_gift_id:
        raise HTTPException(400, "this TikTok gift ID is already mapped to another game gift")


@combo_router.get("", response_model=list[ComboTierOut])
async def list_combo_tiers(db: AsyncSession = Depends(get_db)):
    tiers = (await db.execute(select(ComboTier))).scalars().all()
    return sorted(tiers, key=lambda t: t.threshold)


@combo_router.post("", response_model=ComboTierOut)
async def create_combo_tier(body: ComboTierIn, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    tier = ComboTier(**body.model_dump())
    db.add(tier)
    await db.commit()
    await db.refresh(tier)
    await gift_cache.refresh(db)
    return tier


@combo_router.put("/{tier_id}", response_model=ComboTierOut)
async def update_combo_tier(
    tier_id: str, body: ComboTierIn, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    tier = await db.get(ComboTier, tier_id)
    if not tier:
        raise HTTPException(404, "combo tier not found")
    for k, v in body.model_dump().items():
        setattr(tier, k, v)
    await db.commit()
    await db.refresh(tier)
    await gift_cache.refresh(db)
    return tier


@combo_router.delete("/{tier_id}")
async def delete_combo_tier(tier_id: str, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    tier = await db.get(ComboTier, tier_id)
    if not tier:
        raise HTTPException(404, "combo tier not found")
    await db.delete(tier)
    await db.commit()
    await gift_cache.refresh(db)
    return {"ok": True}
