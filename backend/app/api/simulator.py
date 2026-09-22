import os
import random
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.core.config import settings
from app.core.database import get_db
from app.models.models import Battle, BattleSession, SimulatorProfile
from app.providers.simulation_provider import simulation_provider
from app.schemas.schemas import (
    SimulateGiftRequest,
    SimulatorAutoStartIn,
    SimulatorProfileIn,
    SimulatorProfileOut,
)
from app.services.settings_service import settings_service
from app.services.simulator_autopilot import simulator_autopilot
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
async def simulate_join(
    session_id: str,
    username: str | None = None,
    avatar_url: str | None = None,
    nickname: str | None = None,
    profile_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Make a manual simulated arrival visible in every game mode.

    The name and the photo are honoured when given, whether they come from a
    saved profile or straight from the form. They used to be ignored outright
    -- the endpoint invented a random name and pinned every avatar to an
    external placeholder service -- so registering a photo had no visible
    effect, and a machine that could not reach that service showed no photos.

    Tank war has a deliberate extra rule: real viewers choose A/B in chat.
    The simulator mirrors that chat action immediately after the join, so its
    new profile enters an actual team instead of being an invisible viewer.
    """
    profile = await db.get(SimulatorProfile, profile_id) if profile_id else None
    if profile_id and profile is None:
        raise HTTPException(404, "perfil do simulador não encontrado")
    session = await db.get(BattleSession, session_id)
    battle = await db.get(Battle, session.battle_id) if session else None
    if session is None or battle is None:
        raise HTTPException(404, "sessão da batalha não encontrada")
    name = username or (
        f"{profile.name}_{random.randint(1, 9999)}" if profile else random.choice(_FAKE_USERNAMES) + str(random.randint(1, 9999))
    )
    # An explicit photo wins over the profile's, and the placeholder is only
    # reached when nobody supplied one at all.
    avatar_url = avatar_url or (profile.avatar_url if profile else None) or _placeholder_avatar(name)
    await simulation_provider.simulate_join(
        session_id=session_id,
        user_id=f"sim-{name}",
        username=name,
        nickname=nickname or name,
        avatar_url=avatar_url,
    )
    team = None
    if battle and battle.mode == "tank_war":
        tank = await settings_service.get(db, "tank_war")
        team = random.choice(["A", "B"])
        word = str(tank.get("team_a_keyword" if team == "A" else "team_b_keyword", team))
        await simulation_provider.simulate_comment(
            session_id=session_id,
            user_id=f"sim-{name}",
            username=name,
            nickname=nickname or name,
            avatar_url=avatar_url,
            text=word,
        )
    return {"ok": True, "username": name, "avatar_url": avatar_url, "team": team}


def _placeholder_avatar(name: str) -> str:
    """A stand-in face for a viewer nobody gave a photo to.

    Kept as a remote service only because it is the cheapest way to get a
    hundred distinct faces for a stress test. Anything that actually matters
    -- a photo you registered -- is served from this application instead, so
    it keeps working on a machine with no route to the open internet.
    """
    return f"https://i.pravatar.cc/150?u={name}"


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
    session_id: str,
    gift_keys: list[str],
    user_count: int = 100,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Section 46: SIMULAR LIVE LOTADA. Generates a burst of joins and
    gifts through the normal pipeline so FPS/latency/queue depth can be
    observed under load."""
    session = await db.get(BattleSession, session_id)
    battle = await db.get(Battle, session.battle_id) if session else None
    if session is None or battle is None:
        raise HTTPException(404, "sessão da batalha não encontrada")
    tank = await settings_service.get(db, "tank_war") if battle and battle.mode == "tank_war" else {}
    for i in range(user_count):
        name = f"stress{i}_{random.randint(1, 999999)}"
        await simulation_provider.simulate_join(
            session_id=session_id,
            user_id=f"sim-{name}",
            username=name,
            nickname=name,
            avatar_url=f"https://i.pravatar.cc/150?u={name}",
        )
        if battle and battle.mode == "tank_war":
            await simulation_provider.simulate_comment(
                session_id=session_id,
                user_id=f"sim-{name}",
                username=name,
                nickname=name,
                avatar_url=f"https://i.pravatar.cc/150?u={name}",
                text=random.choice([
                    str(tank.get("team_a_keyword", "A")),
                    str(tank.get("team_b_keyword", "B")),
                ]),
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


@router.get("/profiles", response_model=list[SimulatorProfileOut])
async def list_profiles(db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    return (await db.execute(select(SimulatorProfile).order_by(SimulatorProfile.created_at.desc()))).scalars().all()


@router.post("/profiles", response_model=SimulatorProfileOut)
async def create_profile(
    body: SimulatorProfileIn,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    profile = SimulatorProfile(**body.model_dump())
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.delete("/profiles/{profile_id}")
async def delete_profile(
    profile_id: str, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    profile = await db.get(SimulatorProfile, profile_id)
    if not profile:
        raise HTTPException(404, "perfil do simulador não encontrado")
    await db.delete(profile)
    await db.commit()
    return {"ok": True}


@router.post("/upload")
async def upload_simulator_image(file: UploadFile, _: str = Depends(require_admin)):
    """Stores a simulator face or arena backdrop beside the other assets."""
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(415, "envie uma imagem")
    os.makedirs(settings.upload_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        ext = ".png"
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.upload_dir, filename)
    with open(path, "wb") as stored:
        stored.write(await file.read())
    return {"url": f"/uploads/{filename}"}


@router.get("/auto")
async def auto_status(session_id: str, _: str = Depends(require_admin)):
    return {"session_id": session_id, "running": simulator_autopilot.is_running(session_id)}


@router.post("/auto/start")
async def start_auto(
    body: SimulatorAutoStartIn,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    session = await db.get(BattleSession, body.session_id)
    if session is None or session.status == "finished":
        raise HTTPException(409, "a sessão da batalha não está ativa")
    profiles = (
        await db.execute(
            select(SimulatorProfile).where(SimulatorProfile.id.in_(body.profile_ids))
            if body.profile_ids
            else select(SimulatorProfile)
        )
    ).scalars().all()
    if body.profile_ids and len(profiles) != len(set(body.profile_ids)):
        raise HTTPException(400, "um ou mais perfis do simulador não existem")
    await simulator_autopilot.start(body.session_id, profiles)
    return {"ok": True, "running": True, "profiles": len(profiles)}


@router.post("/auto/stop")
async def stop_auto(session_id: str, _: str = Depends(require_admin)):
    await simulator_autopilot.stop(session_id)
    return {"ok": True, "running": False}
