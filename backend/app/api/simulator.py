import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.core.database import get_db
from app.providers.simulation_provider import simulation_provider
from app.schemas.schemas import SimulateGiftRequest
from app.services.gift_catalog_service import gift_catalog_service
from app.services.gift_repository import gift_repository

router = APIRouter(prefix="/api/simulator", tags=["simulator"])

_FAKE_USERNAMES = [
    "carlos", "ana", "joao", "maria", "pedro", "lucas", "julia", "bruno",
    "camila", "rafael", "fernanda", "gustavo", "larissa", "thiago", "bianca",
]


@router.post("/gift")
async def simulate_gift(body: SimulateGiftRequest, _: str = Depends(require_admin)):
    """Executes exactly the same pipeline a real TikTok gift would trigger
    (spec section 45: no separate simulated-vs-real animation logic)."""
    user_id = f"sim-{body.username}"
    await simulation_provider.simulate_gift(
        session_id=body.session_id,
        user_id=user_id,
        username=body.username,
        gift_key=body.gift_key,
        quantity=body.quantity,
        nickname=body.nickname or body.username,
        avatar_url=body.avatar_url,
    )
    return {"ok": True}


class SimulateCatalogGiftRequest(BaseModel):
    session_id: str
    catalog_id: str
    username: str = "teste"
    quantity: int = 1
    nickname: str | None = None
    avatar_url: str | None = None


@router.post("/catalog-gift")
async def simulate_catalog_gift(
    body: SimulateCatalogGiftRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Send a gift straight from the captured catalogue.

    This is how a rule gets tested without waiting for a real viewer: it
    replays the gift with its real platform ID, so it exercises the same
    normalizer, catalogue, streak guard and rule engine a live gift does.
    """
    entry = await gift_repository.get_by_id(db, body.catalog_id)
    if entry is None:
        raise HTTPException(404, "presente não está no catálogo")

    await simulation_provider.simulate_catalog_gift(
        session_id=body.session_id,
        user_id=f"sim-{body.username}",
        username=body.username,
        platform=entry.platform,
        platform_gift_id=entry.platform_gift_id,
        gift_name=entry.name or entry.platform_gift_id,
        quantity=max(1, body.quantity),
        diamond_value=entry.diamond_value,
        image_url=gift_catalog_service.display_image(entry),
        nickname=body.nickname or body.username,
        avatar_url=body.avatar_url,
    )
    return {
        "ok": True,
        "gift": entry.name or entry.platform_gift_id,
        "platform_gift_id": entry.platform_gift_id,
        "quantity": max(1, body.quantity),
    }


class SimulatePlatformGiftRequest(BaseModel):
    """A gift arriving straight from a platform, ID and all.

    Used to rehearse discovery: it is the only way to see a never-before-seen
    gift ID flow through capture without waiting for a real viewer to send one.
    """

    session_id: str
    platform_gift_id: str
    platform: str = "tiktok"
    name: str | None = None
    image_url: str | None = None
    diamond_value: int | None = None
    username: str = "teste"
    quantity: int = 1
    #: Set to replay an intermediate streak event rather than a complete gift.
    repeat_end: bool = True


@router.post("/platform-gift")
async def simulate_platform_gift(
    body: SimulatePlatformGiftRequest, _: str = Depends(require_admin)
):
    await simulation_provider.simulate_catalog_gift(
        session_id=body.session_id,
        user_id=f"sim-{body.username}",
        username=body.username,
        platform=body.platform,
        platform_gift_id=body.platform_gift_id,
        gift_name=body.name or body.platform_gift_id,
        quantity=max(1, body.quantity),
        diamond_value=body.diamond_value,
        image_url=body.image_url,
        nickname=body.username,
        avatar_url=f"https://i.pravatar.cc/150?u={body.username}",
        repeat_end=body.repeat_end,
    )
    return {"ok": True, "platform_gift_id": body.platform_gift_id}


@router.post("/join")
async def simulate_join(session_id: str, username: str | None = None, _: str = Depends(require_admin)):
    name = username or random.choice(_FAKE_USERNAMES) + str(random.randint(1, 9999))
    await simulation_provider.simulate_join(
        session_id=session_id,
        user_id=f"sim-{name}",
        username=name,
        nickname=name,
        avatar_url=f"https://i.pravatar.cc/150?u={name}",
    )
    return {"ok": True, "username": name}


@router.post("/comment")
async def simulate_comment(
    session_id: str, text: str, username: str | None = None, _: str = Depends(require_admin)
):
    """Tank war mode enlists viewers from chat, so the simulator needs to be
    able to say things as well as send gifts."""
    name = username or random.choice(_FAKE_USERNAMES) + str(random.randint(1, 9999))
    await simulation_provider.simulate_comment(
        session_id=session_id,
        user_id=f"sim-{name}",
        username=name,
        text=text,
        nickname=name,
        avatar_url=f"https://i.pravatar.cc/150?u={name}",
    )
    return {"ok": True, "username": name, "text": text}


@router.post("/stress")
async def simulate_stress(
    session_id: str, gift_keys: list[str], user_count: int = 100, _: str = Depends(require_admin)
):
    """Section 46: SIMULAR LIVE LOTADA. Generates a burst of joins and
    gifts through the normal pipeline so FPS/latency/queue depth can be
    observed under load."""
    for i in range(user_count):
        name = f"stress{i}_{random.randint(1, 999999)}"
        await simulation_provider.simulate_join(
            session_id=session_id,
            user_id=f"sim-{name}",
            username=name,
            nickname=name,
            avatar_url=f"https://i.pravatar.cc/150?u={name}",
        )
        if gift_keys:
            await simulation_provider.simulate_gift(
                session_id=session_id,
                user_id=f"sim-{name}",
                username=name,
                gift_key=random.choice(gift_keys),
                quantity=random.choice([1, 1, 1, 5, 10]),
                nickname=name,
                avatar_url=f"https://i.pravatar.cc/150?u={name}",
            )
    return {"ok": True, "spawned": user_count}
