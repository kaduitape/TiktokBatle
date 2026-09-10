from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Battle, BattleSession, Character
from app.schemas.schemas import BattleIn, BattleOut, SessionOut
from app.services.battle_manager import battle_manager

router = APIRouter(prefix="/api/battles", tags=["battles"])


@router.get("", response_model=list[BattleOut])
async def list_battles(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Battle))).scalars().all()


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
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(404, "battle not found")
    session = await battle_manager.start_session(db, battle)
    await db.commit()
    await db.refresh(session)
    return session
