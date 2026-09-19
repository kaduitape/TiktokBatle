"""Admin API for the automatic gift catalogue.

Everything here is admin-only. The catalogue holds platform IDs, sender
handles and raw provider payloads, none of which may ever reach the public
arena (section 18) -- so unlike /api/settings there is no unauthenticated
read on this router.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.core.database import get_db
from app.models.models import Gift
from app.schemas.schemas import LearningModeIn, LiveGiftOut, LiveGiftRuleIn
from app.services.gift_cache import gift_cache
from app.services.gift_capture_service import gift_capture_service
from app.services.gift_catalog_service import gift_catalog_service
from app.services.gift_repository import gift_repository

router = APIRouter(prefix="/api/live-gifts", tags=["live-gifts"])
logger = logging.getLogger("live_gifts_api")

#: Human labels for the actions, so the panel and the catalogue agree on
#: wording without the frontend having to own a second copy of the list.
ACTION_LABELS = {
    "shot": "Tiro",
    "burst": "Rajada",
    "missile": "Míssil",
    "bomb": "Bomba",
    "meteor": "Meteoro",
    "airstrike": "Ataque aéreo",
    "lightning": "Raio",
    "heal": "Cura",
    "super_heal": "Super Cura",
    "shield": "Escudo",
    "special": "Evento especial",
    "none": "Nenhuma",
}


def _to_out(entry, rule: Gift | None) -> LiveGiftOut:
    return LiveGiftOut(
        id=entry.id,
        platform=entry.platform,
        platform_gift_id=entry.platform_gift_id,
        name=entry.name,
        image_url=gift_catalog_service.display_image(entry),
        diamond_value=entry.diamond_value,
        coin_value=entry.coin_value,
        times_received=entry.times_received or 0,
        first_seen_at=entry.first_seen_at,
        last_seen_at=entry.last_seen_at,
        active=bool(entry.active),
        metadata_json=entry.metadata_json or {},
        configured=rule is not None,
        gift_id=rule.id if rule else None,
        gift_key=rule.gift_key if rule else None,
        action_type=rule.action_type if rule else None,
        action_label=ACTION_LABELS.get(rule.action_type, rule.action_type) if rule else None,
        xp_value=rule.value if rule else None,
        target_side=rule.target_side if rule else None,
        animation_key=rule.animation_key if rule else None,
        sound_key=rule.sound_key if rule else None,
    )


@router.get("", response_model=list[LiveGiftOut])
async def list_catalog(db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    entries = await gift_repository.list_all(db)
    rules = await gift_repository.rules_by_platform_id(db)
    return [_to_out(e, rules.get((e.platform, e.platform_gift_id))) for e in entries]


@router.get("/summary")
async def catalog_summary(db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    """Small, cheap payload the menu badge polls for."""
    entries = await gift_repository.list_all(db)
    rules = await gift_repository.rules_by_platform_id(db)
    configured = sum(1 for e in entries if (e.platform, e.platform_gift_id) in rules)
    return {
        "total": len(entries),
        "configured": configured,
        "unconfigured": len(entries) - configured,
        "learning_mode": await gift_capture_service.learning_mode(db),
        "capturing": gift_capture_service.capturing,
        "discovered_this_session": len(gift_capture_service.discovered()),
    }


@router.put("/{entry_id}/rule", response_model=LiveGiftOut)
async def configure_rule(
    entry_id: str,
    body: LiveGiftRuleIn,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Attach an action to a captured gift, creating the rule if needed.

    The rule is keyed to the catalogue entry's platform and ID. Nothing about
    it depends on the gift's name, which the platform is free to translate or
    rewrite at any time.
    """
    entry = await gift_repository.get_by_id(db, entry_id)
    if entry is None:
        raise HTTPException(404, "presente não está no catálogo")

    rules = await gift_repository.rules_by_platform_id(db)
    gift = rules.get((entry.platform, entry.platform_gift_id))

    if gift is None:
        gift = Gift(
            gift_key=await _unique_gift_key(db, entry),
            platform=entry.platform,
            tiktok_gift_id=entry.platform_gift_id,
            name=entry.name or entry.platform_gift_id,
        )
        db.add(gift)

    gift.name = entry.name or gift.name or entry.platform_gift_id
    gift.image_url = gift_catalog_service.display_image(entry) or gift.image_url
    gift.action_type = body.action_type
    gift.target_side = body.target_side
    gift.value = body.value
    gift.animation_key = body.animation_key
    gift.sound_key = body.sound_key
    gift.multiplier = body.multiplier
    gift.combo_allowed = body.combo_allowed
    gift.active = body.active
    if body.icon:
        gift.icon = body.icon
    # The gift's price is what the platform said it was; only fall back to the
    # form when the catalogue never learned a value.
    gift.coins = entry.diamond_value or body.coins or gift.coins or 1

    await db.commit()
    await db.refresh(gift)
    await gift_cache.refresh(db)
    return _to_out(entry, gift)


@router.delete("/{entry_id}/rule")
async def clear_rule(
    entry_id: str, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    """Unconfigure a gift: it stays in the catalogue and stops acting."""
    entry = await gift_repository.get_by_id(db, entry_id)
    if entry is None:
        raise HTTPException(404, "presente não está no catálogo")
    rules = await gift_repository.rules_by_platform_id(db)
    gift = rules.get((entry.platform, entry.platform_gift_id))
    if gift is None:
        return {"ok": True}
    await db.delete(gift)
    await db.commit()
    await gift_cache.refresh(db)
    return {"ok": True}


@router.post("/learning-mode")
async def set_learning_mode(
    body: LearningModeIn, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    """Learning mode records everything and changes nothing in the game."""
    config = await gift_capture_service.set_learning_mode(db, body.enabled)
    await db.commit()
    return {
        "learning_mode": bool(config.get("learning_mode")),
        "discovered": gift_capture_service.discovered(),
    }


@router.get("/learning-mode")
async def get_learning_mode(db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    return {
        "learning_mode": await gift_capture_service.learning_mode(db),
        "discovered": gift_capture_service.discovered(),
    }


@router.post("/discovered/clear")
async def clear_discovered(_: str = Depends(require_admin)):
    gift_capture_service.clear_discovered()
    return {"ok": True}


@router.get("/monitor")
async def event_monitor(limit: int = 50, _: str = Depends(require_admin)):
    """The raw event tail. Admin-only, and never rendered in the arena."""
    return {"events": gift_capture_service.monitor(min(max(limit, 1), 200))}


@router.post("/capturing")
async def set_capturing(body: LearningModeIn, _: str = Depends(require_admin)):
    gift_capture_service.set_capturing(body.enabled)
    return {"capturing": gift_capture_service.capturing}


@router.post("/sync")
async def sync_catalog(
    session_id: str | None = None, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    """Pull the room's full gift list from the provider, when it offers one.

    This is a convenience, never a requirement: capture by event keeps working
    on its own, and a provider that cannot list its catalogue simply reports
    that here instead of failing.
    """
    from app.services.gift_catalog_sync import gift_catalog_sync

    return await gift_catalog_sync.sync(db, session_id)


async def _unique_gift_key(db: AsyncSession, entry) -> str:
    """A readable key derived from the gift's name, kept unique.

    The key is for humans and for the simulator; the platform ID is what the
    game matches on, so a collision here is a naming inconvenience, not a
    correctness problem.
    """
    base = re.sub(r"[^a-z0-9]+", "_", (entry.name or "").lower()).strip("_")
    if not base:
        base = f"gift_{entry.platform_gift_id}"
    candidate = base
    suffix = 2
    existing = {gift.gift_key for gift in (await gift_repository.rules_by_platform_id(db)).values()}
    from sqlalchemy import select

    all_keys = set((await db.execute(select(Gift.gift_key))).scalars().all()) | existing
    while candidate in all_keys:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate
