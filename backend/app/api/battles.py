from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.core.database import get_db
from app.models.models import Battle, BattleEvent, BattleGift, BattleSession, Character, Gift, Player
from app.schemas.schemas import ActiveBattleOut, BattleGiftsIn, BattleIn, BattleOut, SessionOut
from app.services import arena_analysis
from app.services.battle_manager import battle_manager
from app.services.gift_cache import gift_cache
from app.services.state_sync import build_state_sync
from app.ws.connection_manager import connection_manager

router = APIRouter(prefix="/api/battles", tags=["battles"])
ACTIVE_SESSION_STATUSES = ("active", "sudden_death")


async def _validate_sides(db: AsyncSession, body: BattleIn) -> None:
    """Ensure a battle has two characters with distinct artwork."""
    if body.side_a_character_id == body.side_b_character_id:
        raise HTTPException(422, "side_a_character_id and side_b_character_id must be different")

    side_a = await db.get(Character, body.side_a_character_id)
    side_b = await db.get(Character, body.side_b_character_id)
    if not side_a or not side_b:
        missing_id = body.side_a_character_id if not side_a else body.side_b_character_id
        raise HTTPException(400, f"character {missing_id} not found")
    if side_a.image_url and side_a.image_url == side_b.image_url:
        raise HTTPException(422, "side_a and side_b must use different character images")


@router.get("", response_model=list[BattleOut])
async def list_battles(db: AsyncSession = Depends(get_db)):
    """Templates are excluded here -- they aren't playable battles, they're
    reusable configs. Fetch them via GET /api/battles/templates."""
    return (
        (await db.execute(select(Battle).where(Battle.is_template.is_(False))))
        .scalars()
        .all()
    )


@router.get("/templates", response_model=list[BattleOut])
async def list_templates(db: AsyncSession = Depends(get_db)):
    """Registered before /{battle_id} on purpose -- 'templates' would
    otherwise be swallowed as a battle_id path parameter (spec section 44:
    salvar/reutilizar modelos de batalha como 'Política', 'Futebol' etc,
    quaisquer nomes que o admin quiser)."""
    return (
        (await db.execute(select(Battle).where(Battle.is_template.is_(True))))
        .scalars()
        .all()
    )


@router.post("", response_model=BattleOut)
async def create_battle(body: BattleIn, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    await _validate_sides(db, body)
    battle = Battle(**body.model_dump())
    db.add(battle)
    await db.commit()
    await db.refresh(battle)
    return battle


@router.get("/active", response_model=ActiveBattleOut)
async def get_current_active_battle(db: AsyncSession = Depends(get_db)):
    """Resolve simulation to the most recently started live battle.

    The simulator used to start the first battle in the list, even when OBS
    was showing another one. Resolving the live session here keeps all events
    on the battle currently in progress.
    """
    session = (
        await db.execute(
            select(BattleSession)
            .where(BattleSession.status.in_(ACTIVE_SESSION_STATUSES))
            .order_by(BattleSession.started_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if not session:
        raise HTTPException(404, "no active battle session")

    battle = await db.get(Battle, session.battle_id)
    if not battle:
        raise HTTPException(404, "active battle not found")
    return {"battle": battle, "session": session}


@router.get("/{battle_id}", response_model=BattleOut)
async def get_battle(battle_id: str, db: AsyncSession = Depends(get_db)):
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")
    return battle


@router.put("/{battle_id}", response_model=BattleOut)
async def update_battle(
    battle_id: str, body: BattleIn, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    await _validate_sides(db, body)
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")
    for k, v in body.model_dump().items():
        setattr(battle, k, v)
    await db.commit()
    await db.refresh(battle)
    return battle


@router.delete("/{battle_id}")
async def delete_battle(battle_id: str, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    """Deleting a battle takes its history with it.

    A battle owns sessions, which own players and events. Nothing declares a
    cascade, so removing only the battle row left those children pointing at
    nothing: PostgreSQL rejected it and the panel showed a button that did
    nothing. Clear the children first, deepest first.
    """
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")

    session_ids = (
        (await db.execute(select(BattleSession.id).where(BattleSession.battle_id == battle_id)))
        .scalars()
        .all()
    )
    if session_ids:
        await db.execute(delete(BattleEvent).where(BattleEvent.session_id.in_(session_ids)))
        await db.execute(delete(Player).where(Player.session_id.in_(session_ids)))
        await db.execute(delete(BattleSession).where(BattleSession.id.in_(session_ids)))

    await db.delete(battle)
    await db.commit()
    return {"ok": True, "sessions_removed": len(session_ids)}


@router.post("/{battle_id}/start", response_model=SessionOut)
async def start_battle(battle_id: str, db: AsyncSession = Depends(get_db)):
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")

    existing = await battle_manager.get_active_session(db, battle_id)
    if existing:
        return existing

    session = await battle_manager.start_session(db, battle)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/{battle_id}/session", response_model=SessionOut)
async def get_active_session(battle_id: str, db: AsyncSession = Depends(get_db)):
    session = await battle_manager.get_active_session(db, battle_id)
    if not session:
        raise HTTPException(404, "no active session for this battle")
    return session


@router.post("/{battle_id}/restart", response_model=SessionOut)
async def restart_battle(battle_id: str, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    """Manual 'nova rodada' (section 40): resets XP in place on the
    existing session so connected arenas don't need to reconnect, or
    starts a fresh session if none exists yet."""
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")

    existing = await battle_manager.get_active_session(db, battle_id)
    if existing:
        session = await battle_manager.restart_session(db, existing, battle)
    else:
        session = await battle_manager.start_session(db, battle)

    await db.commit()
    await db.refresh(session)

    side_a = await db.get(Character, battle.side_a_character_id)
    side_b = await db.get(Character, battle.side_b_character_id)
    await connection_manager.broadcast(
        session.id,
        {
            "type": "battle_restarted",
            "session_id": session.id,
            "xp": {"a": session.side_a_xp, "b": session.side_b_xp},
            "xp_max": {"a": side_a.xp_max, "b": side_b.xp_max},
        },
    )

    # Followed by the whole picture, so a restart also republishes the
    # characters. Swapping a character's artwork in the panel and hitting
    # "reiniciar" then updates an OBS source that is already open, instead of
    # needing it closed and reopened.
    state = await build_state_sync(session.id)
    if state:
        await connection_manager.broadcast(session.id, state)
    return session


@router.get("/{battle_id}/analysis")
async def analyse_battle(battle_id: str, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    """Reads the battle's configuration and reports what would hurt the live.
    It checks data, not the stream, so it never claims a battle is 'approved'."""
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")
    return await arena_analysis.analyse(db, battle)


@router.get("/{battle_id}/gifts")
async def get_battle_gifts(battle_id: str, db: AsyncSession = Depends(get_db)):
    """The gift ids this battle accepts. An empty list means every active
    gift -- the panel shows that as 'todos'."""
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")
    gift_ids = (
        (await db.execute(select(BattleGift.gift_id).where(BattleGift.battle_id == battle_id)))
        .scalars()
        .all()
    )
    return {"battle_id": battle_id, "gift_ids": list(gift_ids), "all_gifts": not gift_ids}


@router.put("/{battle_id}/gifts")
async def set_battle_gifts(
    battle_id: str,
    body: BattleGiftsIn,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")

    known = set(
        (await db.execute(select(Gift.id).where(Gift.id.in_(body.gift_ids)))).scalars().all()
    ) if body.gift_ids else set()
    unknown = [g for g in body.gift_ids if g not in known]
    if unknown:
        raise HTTPException(400, f"presente desconhecido: {', '.join(unknown)}")

    await db.execute(delete(BattleGift).where(BattleGift.battle_id == battle_id))
    for gift_id in dict.fromkeys(body.gift_ids):
        db.add(BattleGift(battle_id=battle_id, gift_id=gift_id))
    await db.commit()
    gift_cache.invalidate_battle(battle_id)
    return {"battle_id": battle_id, "gift_ids": body.gift_ids, "all_gifts": not body.gift_ids}


@router.post("/{battle_id}/save-as-template", response_model=BattleOut)
async def save_as_template(
    battle_id: str, template_name: str, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    """Spec section 44: clones this battle's full configuration into a
    reusable template row an admin can instantiate later under any name."""
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")

    template = Battle(
        name=template_name,
        side_a_character_id=battle.side_a_character_id,
        side_b_character_id=battle.side_b_character_id,
        background_url=battle.background_url,
        max_players=battle.max_players,
        one_ball_per_user=battle.one_ball_per_user,
        battle_time_seconds=battle.battle_time_seconds,
        sudden_death_enabled=battle.sudden_death_enabled,
        sudden_death_multiplier=battle.sudden_death_multiplier,
        auto_restart=battle.auto_restart,
        is_template=True,
        template_name=template_name,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@router.post("/from-template/{template_id}", response_model=BattleOut)
async def instantiate_template(
    template_id: str, name: str, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    template = await db.get(Battle, template_id)
    if not template or not template.is_template:
        raise HTTPException(404, "template not found")

    battle = Battle(
        name=name,
        side_a_character_id=template.side_a_character_id,
        side_b_character_id=template.side_b_character_id,
        background_url=template.background_url,
        max_players=template.max_players,
        one_ball_per_user=template.one_ball_per_user,
        battle_time_seconds=template.battle_time_seconds,
        sudden_death_enabled=template.sudden_death_enabled,
        sudden_death_multiplier=template.sudden_death_multiplier,
        auto_restart=template.auto_restart,
        is_template=False,
    )
    db.add(battle)
    await db.commit()
    await db.refresh(battle)
    return battle
