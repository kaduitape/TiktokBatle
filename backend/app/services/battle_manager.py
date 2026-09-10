from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Battle, BattleSession, Character


class BattleManager:
    """Owns BattleSession lifecycle: starting a fresh run of a Battle
    template, and detecting/declaring victory when a side's XP hits zero."""

    @staticmethod
    async def start_session(db: AsyncSession, battle: Battle) -> BattleSession:
        side_a = await db.get(Character, battle.side_a_character_id)
        side_b = await db.get(Character, battle.side_b_character_id)

        ends_at = None
        if battle.battle_time_seconds:
            ends_at = datetime.now(timezone.utc) + timedelta(seconds=battle.battle_time_seconds)

        session = BattleSession(
            battle_id=battle.id,
            side_a_xp=side_a.xp_max,
            side_b_xp=side_b.xp_max,
            status="active",
            ends_at=ends_at,
        )
        db.add(session)
        await db.flush()
        return session

    @staticmethod
    async def get_active_session(db: AsyncSession, battle_id: str) -> BattleSession | None:
        return (
            await db.execute(
                select(BattleSession)
                .where(BattleSession.battle_id == battle_id, BattleSession.status != "finished")
                .order_by(BattleSession.started_at.desc())
            )
        ).scalars().first()

    @staticmethod
    def check_victory(session: BattleSession) -> str | None:
        if session.status == "finished":
            return session.winner_side
        if session.side_a_xp <= 0:
            session.status = "finished"
            session.winner_side = "B"
            session.finished_at = datetime.now(timezone.utc)
        elif session.side_b_xp <= 0:
            session.status = "finished"
            session.winner_side = "A"
            session.finished_at = datetime.now(timezone.utc)
        return session.winner_side


battle_manager = BattleManager()
