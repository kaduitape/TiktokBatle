from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Battle, Character
from app.schemas.schemas import BattleIn, BattleOut, SessionOut
from app.services.battle_manager import battle_manager
from app.ws.connection_manager import connection_manager

router = APIRouter(prefix="/api/battles", tags=["battles"])


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
async def create_battle(body: BattleIn, db: AsyncSession = Depends(get_db)):
    for cid in (body.side_a_character_id, body.side_b_character_id):
        if not await db.get(Character, cid):
            raise HTTPException(400, f"character {cid} not found")
    battle = Battle(**body.model_dump())
    db.add(battle)
    await db.commit()
    await db.refresh(battle)
    return battle


@router.get("/{battle_id}", response_model=BattleOut)
async def get_battle(battle_id: str, db: AsyncSession = Depends(get_db)):
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")
    return battle


@router.put("/{battle_id}", response_model=BattleOut)
async def update_battle(battle_id: str, body: BattleIn, db: AsyncSession = Depends(get_db)):
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")
    for k, v in body.model_dump().items():
        setattr(battle, k, v)
    await db.commit()
    await db.refresh(battle)
    return battle


@router.delete("/{battle_id}")
async def delete_battle(battle_id: str, db: AsyncSession = Depends(get_db)):
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")
    await db.delete(battle)
    await db.commit()
    return {"ok": True}


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
async def restart_battle(battle_id: str, db: AsyncSession = Depends(get_db)):
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
    return session


@router.post("/{battle_id}/save-as-template", response_model=BattleOut)
async def save_as_template(battle_id: str, template_name: str, db: AsyncSession = Depends(get_db)):
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
async def instantiate_template(template_id: str, name: str, db: AsyncSession = Depends(get_db)):
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
