from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import ComboTier, Gift
from app.schemas.schemas import ComboTierIn, ComboTierOut, GiftIn, GiftOut
from app.services.gift_cache import gift_cache

router = APIRouter(prefix="/api/gifts", tags=["gifts"])
combo_router = APIRouter(prefix="/api/combo-tiers", tags=["combo-tiers"])


@router.get("", response_model=list[GiftOut])
async def list_gifts(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Gift))).scalars().all()


@router.post("", response_model=GiftOut)
async def create_gift(body: GiftIn, db: AsyncSession = Depends(get_db)):
    existing = (
        await db.execute(select(Gift).where(Gift.gift_key == body.gift_key))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "gift_key already exists")
    gift = Gift(**body.model_dump())
    db.add(gift)
    await db.commit()
    await db.refresh(gift)
    await gift_cache.refresh(db)
    return gift


@router.put("/{gift_id}", response_model=GiftOut)
async def update_gift(gift_id: str, body: GiftIn, db: AsyncSession = Depends(get_db)):
    gift = await db.get(Gift, gift_id)
    if not gift:
        raise HTTPException(404, "gift not found")
    for k, v in body.model_dump().items():
        setattr(gift, k, v)
    await db.commit()
    await db.refresh(gift)
    await gift_cache.refresh(db)
    return gift


@router.delete("/{gift_id}")
async def delete_gift(gift_id: str, db: AsyncSession = Depends(get_db)):
    gift = await db.get(Gift, gift_id)
    if not gift:
        raise HTTPException(404, "gift not found")
    await db.delete(gift)
    await db.commit()
    await gift_cache.refresh(db)
    return {"ok": True}


@combo_router.get("", response_model=list[ComboTierOut])
async def list_combo_tiers(db: AsyncSession = Depends(get_db)):
    tiers = (await db.execute(select(ComboTier))).scalars().all()
    return sorted(tiers, key=lambda t: t.threshold)


@combo_router.post("", response_model=ComboTierOut)
async def create_combo_tier(body: ComboTierIn, db: AsyncSession = Depends(get_db)):
    tier = ComboTier(**body.model_dump())
    db.add(tier)
    await db.commit()
    await db.refresh(tier)
    await gift_cache.refresh(db)
    return tier


@combo_router.put("/{tier_id}", response_model=ComboTierOut)
async def update_combo_tier(tier_id: str, body: ComboTierIn, db: AsyncSession = Depends(get_db)):
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
async def delete_combo_tier(tier_id: str, db: AsyncSession = Depends(get_db)):
    tier = await db.get(ComboTier, tier_id)
    if not tier:
        raise HTTPException(404, "combo tier not found")
    await db.delete(tier)
    await db.commit()
    await gift_cache.refresh(db)
    return {"ok": True}
