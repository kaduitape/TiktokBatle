from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Player
from app.schemas.schemas import RankingEntry
from app.services.ranking_manager import ranking_manager

router = APIRouter(prefix="/api", tags=["players"])


@router.get("/sessions/{session_id}/players")
async def list_players(session_id: str, db: AsyncSession = Depends(get_db)):
    players = (
        (await db.execute(select(Player).where(Player.session_id == session_id)))
        .scalars()
        .all()
    )
    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "username": p.username,
            "nickname": p.nickname,
            "avatar_url": p.avatar_url,
            "team": p.team,
            "damage_total": p.damage_total,
            "heal_total": p.heal_total,
            "gifts_total": p.gifts_total,
            "combo_count": p.combo_count,
        }
        for p in players
    ]


@router.get("/sessions/{session_id}/ranking", response_model=list[RankingEntry])
async def get_ranking(session_id: str, limit: int = 10, db: AsyncSession = Depends(get_db)):
    return await ranking_manager.top(db, session_id, limit)
