from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Battle, BattleSession, Character, Player


def _as_utc(dt: datetime) -> datetime:
    """SQLite (used in dev/tests) drops tzinfo on round-trip even for
    TIMESTAMP WITH TIME ZONE columns, while Postgres preserves it -- treat
    a naive datetime read back from the DB as UTC either way."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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

    @classmethod
    async def restart_session(
        cls, db: AsyncSession, session: BattleSession, battle: Battle
    ) -> BattleSession:
        """Resets an existing session in place (same session_id, so
        connected OBS/WebSocket clients don't need to reconnect) -- used
        for both manual and auto-restart 'nova rodada' (spec section 40)."""
        side_a = await db.get(Character, battle.side_a_character_id)
        side_b = await db.get(Character, battle.side_b_character_id)

        session.side_a_xp = side_a.xp_max
        session.side_b_xp = side_b.xp_max
        session.status = "active"
        session.winner_side = None
        session.finished_at = None
        session.ends_at = (
            datetime.now(timezone.utc) + timedelta(seconds=battle.battle_time_seconds)
            if battle.battle_time_seconds
            else None
        )

        if battle.mode == "team_pvp":
            await cls._reset_fighters(db, session.id)

        await db.flush()
        return session

    @staticmethod
    async def _reset_fighters(db: AsyncSession, session_id: str) -> None:
        """A new PvP round revives everyone at their starting power so the
        viewers already in the arena keep playing without rejoining."""
        from app.services.settings_service import settings_service
        from app.services.team_battle_manager import team_battle_manager

        config = await settings_service.get(db, "team_battle")
        starting = team_battle_manager.starting_power(config)

        players = (
            (await db.execute(select(Player).where(Player.session_id == session_id))).scalars().all()
        )
        for player in players:
            player.power = starting
            player.level = team_battle_manager.level_for(starting, config)
            player.eliminated = False

    @staticmethod
    def check_sudden_death(session: BattleSession, battle: Battle) -> bool:
        """Spec section 37: once the battle timer runs out, switch into
        morte súbita with escalating damage multipliers instead of just
        ending the battle. Returns True the moment the transition happens
        so the caller can broadcast it once."""
        if not battle.sudden_death_enabled or session.status != "active" or not session.ends_at:
            return False
        if datetime.now(timezone.utc) >= _as_utc(session.ends_at):
            session.status = "sudden_death"
            return True
        return False

    @staticmethod
    def sudden_death_multiplier(session: BattleSession, battle: Battle) -> float:
        if session.status != "sudden_death" or not session.ends_at:
            return 1.0
        elapsed = (datetime.now(timezone.utc) - _as_utc(session.ends_at)).total_seconds()
        base = battle.sudden_death_multiplier or 2.0
        return base * 1.5 if elapsed > 60 else base

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
