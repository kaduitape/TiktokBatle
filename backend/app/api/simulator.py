import os
import logging
import random
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.core.config import settings
from app.core.database import get_db
from app.models.models import Battle, BattleEvent, BattleSession, Player, SimulatorProfile
from app.providers.simulation_provider import simulation_provider
from app.schemas.schemas import (
    SimulateGiftRequest,
    SimulatorAutoStartIn,
    SimulatorProfileIn,
    SimulatorProfileOut,
)
from app.services.battle_manager import battle_manager
from app.services.combo_manager import combo_manager
from app.services.gift_streak_guard import gift_streak_guard
from app.services.settings_service import settings_service
from app.services.state_sync import build_state_sync
from app.ws.connection_manager import connection_manager
from app.services.simulator_autopilot import simulator_autopilot
from app.services.gift_catalog_service import gift_catalog_service
from app.services.gift_repository import gift_repository

router = APIRouter(prefix="/api/simulator", tags=["simulator"])
logger = logging.getLogger("simulator")

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
    attacks_each: int = 2,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """A packed LIVE: a burst of arrivals, each one attacking the rival boss.

    Two rules make it behave like a real room rather than a counter:

    * **Nobody joins twice.** A name already on the field is skipped, so
      running this again tops the arena up instead of doubling it.
    * **Only the eliminated come back.** Somebody knocked out returns and
      picks a side again, which is exactly what a real viewer does.

    Everybody who gets in then attacks the enemy boss with random gifts, so
    the load being measured is the one the game actually carries.
    """
    session = await db.get(BattleSession, session_id)
    battle = await db.get(Battle, session.battle_id) if session else None
    if session is None or battle is None:
        raise HTTPException(404, "sessão da batalha não encontrada")

    tank = await settings_service.get(db, "tank_war") if battle.mode == "tank_war" else {}
    keywords = [str(tank.get("team_a_keyword", "A")), str(tank.get("team_b_keyword", "B"))]

    existing = (
        (await db.execute(select(Player).where(Player.session_id == session.id))).scalars().all()
    )
    # A name still standing is already playing. One that was knocked out is
    # free to come back; everybody else is a newcomer.
    alive = {p.username for p in existing if not p.eliminated and (p.power or 0) > 0}
    returning = [p.username for p in existing if p.username not in alive]

    joined: list[str] = []
    reused = 0
    for _index in range(user_count):
        if returning:
            name = returning.pop()
            reused += 1
        else:
            # Unique by construction, and unique against what is already
            # there: a repeated name would be the same viewer, not a new one.
            name = f"stress{uuid.uuid4().hex[:8]}"
            if name in alive:
                continue
        alive.add(name)
        joined.append(name)

    for name in joined:
        user_id = f"sim-{name}"
        avatar = f"https://i.pravatar.cc/150?u={name}"
        await simulation_provider.simulate_join(
            session_id=session_id,
            user_id=user_id,
            username=name,
            nickname=name,
            avatar_url=avatar,
        )
        if battle.mode == "tank_war":
            # Without a side, a tank war gift is ignored outright.
            await simulation_provider.simulate_comment(
                session_id=session_id,
                user_id=user_id,
                username=name,
                nickname=name,
                avatar_url=avatar,
                text=random.choice(keywords),
            )
        for _shot in range(max(0, attacks_each)):
            if not gift_keys:
                break
            await simulation_provider.simulate_gift(
                session_id=session_id,
                user_id=user_id,
                username=name,
                gift_key=random.choice(gift_keys),
                quantity=random.choice([1, 1, 1, 5, 10]),
                nickname=name,
                avatar_url=avatar,
            )

    return {
        "ok": True,
        "spawned": len(joined),
        "returning": reused,
        "attacks": len(joined) * max(0, attacks_each) if gift_keys else 0,
    }


class ResetIn(BaseModel):
    session_id: str
    #: Also put the bosses' health back and clear the clock. Off leaves the
    #: scoreboard where it was and only empties the arena of people.
    restart_battle: bool = True


@router.post("/reset")
async def reset_session(
    body: ResetIn, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    """Empty the arena.

    A stress test leaves a hundred avatars behind, and the next one piles more
    on top. This removes every player from the session -- and, unless told
    otherwise, puts the battle back to its starting state -- then republishes
    the state so an arena already open in OBS clears itself instead of needing
    a reload.
    """
    session = await db.get(BattleSession, body.session_id)
    battle = await db.get(Battle, session.battle_id) if session else None
    if session is None or battle is None:
        raise HTTPException(404, "sessão da batalha não encontrada")

    # Any continuous simulation would immediately refill what we just emptied.
    await simulator_autopilot.stop(body.session_id)

    removed = (
        await db.execute(select(func.count()).select_from(Player).where(Player.session_id == session.id))
    ).scalar_one()
    # Events reference players, so they go first.
    await db.execute(delete(BattleEvent).where(BattleEvent.session_id == session.id))
    await db.execute(delete(Player).where(Player.session_id == session.id))

    if body.restart_battle:
        await battle_manager.restart_session(db, session, battle)
    await db.commit()

    # Combo state is per (session, user); leaving it would let a name that
    # comes back inherit the streak of the one just removed.
    combo_manager.reset_session(session.id)
    gift_streak_guard.reset(session.id)

    state = await build_state_sync(session.id)
    if state:
        await connection_manager.broadcast(session.id, state)

    return {"ok": True, "removed": int(removed), "restarted": body.restart_battle}


def _profile_storage_error(exc: SQLAlchemyError) -> HTTPException:
    """A missing simulator_profiles table reached the panel as a bare
    "Internal Server Error", which says nothing about what to do. Name the
    likely cause instead -- a migration that never ran."""
    logger.exception("falha ao acessar simulator_profiles")
    return HTTPException(
        500,
        "Não consegui ler ou gravar os perfis do simulador. Se o banco não recebeu a "
        "migration 0013 (tabela simulator_profiles), esta tela não funciona: abra "
        "/api/health para conferir quais tabelas estão faltando. Detalhe: "
        f"{type(exc).__name__}.",
    )


@router.get("/profiles", response_model=list[SimulatorProfileOut])
async def list_profiles(db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    try:
        return (
            await db.execute(select(SimulatorProfile).order_by(SimulatorProfile.created_at.desc()))
        ).scalars().all()
    except SQLAlchemyError as exc:
        raise _profile_storage_error(exc) from exc


@router.post("/profiles", response_model=SimulatorProfileOut)
async def create_profile(
    body: SimulatorProfileIn,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    profile = SimulatorProfile(**body.model_dump())
    db.add(profile)
    try:
        await db.commit()
        await db.refresh(profile)
    except SQLAlchemyError as exc:
        await db.rollback()
        raise _profile_storage_error(exc) from exc
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


#: Extensions the panel accepts for a face or a backdrop.
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@router.post("/upload")
async def upload_simulator_image(file: UploadFile, _: str = Depends(require_admin)):
    """Stores a simulator face or arena backdrop beside the other assets."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    declared = (file.content_type or "").lower()
    # Some browsers label a perfectly good PNG as application/octet-stream, so
    # the extension gets a say. A .txt is still refused by both.
    if not declared.startswith("image/") and ext not in _IMAGE_EXTENSIONS:
        raise HTTPException(
            415,
            f"Isto não parece uma imagem ({declared or 'tipo desconhecido'}). "
            "Envie um arquivo .png, .jpg, .webp ou .gif.",
        )
    if ext not in _IMAGE_EXTENSIONS:
        ext = ".png"
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.upload_dir, filename)
    payload = await file.read()
    if not payload:
        raise HTTPException(400, "O arquivo chegou vazio. Tente escolher a imagem de novo.")
    try:
        os.makedirs(settings.upload_dir, exist_ok=True)
        with open(path, "wb") as stored:
            stored.write(payload)
    except OSError as exc:
        # A read-only or missing uploads volume produced a bare 500, which in
        # the panel was indistinguishable from a button that does nothing.
        logger.exception("não consegui gravar o upload em %s", path)
        raise HTTPException(
            500,
            f"Não consegui gravar a imagem em {settings.upload_dir} ({exc.strerror or exc}). "
            "Confira se o volume de uploads existe e tem permissão de escrita no servidor.",
        ) from exc
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
