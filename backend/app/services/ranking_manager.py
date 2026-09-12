from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Player
from app.schemas.schemas import RankingEntry


class RankingManager:
    """Computes the leaderboard for a session from live player_stats rows.
    Score favours damage/heal contribution plus a combo bonus."""

    @staticmethod
    async def top(db: AsyncSession, session_id: str, limit: int = 10) -> list[RankingEntry]:
        players = (
            (await db.execute(select(Player).where(Player.session_id == session_id)))
            .scalars()
            .all()
        )

        def score(p: Player) -> float:
            # power/kills are always 0 outside team PvP, so the same formula
            # ranks both modes without branching.
            return p.damage_total + p.heal_total + p.combo_count * 10 + p.power + p.kills * 100

        ranked = sorted(players, key=score, reverse=True)[:limit]
        return [
            RankingEntry(
                user_id=p.user_id,
                username=p.username,
                nickname=p.nickname,
                avatar_url=p.avatar_url,
                team=p.team,
                damage_total=p.damage_total,
                heal_total=p.heal_total,
                gifts_total=p.gifts_total,
                combo_count=p.combo_count,
                power=p.power,
                kills=p.kills,
                score=score(p),
            )
            for p in ranked
        ]


ranking_manager = RankingManager()
