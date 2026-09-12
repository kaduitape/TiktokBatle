import asyncio
import logging
from datetime import datetime, timezone

from app.core.database import AsyncSessionLocal
from app.models.models import Battle, BattleSession
from app.services.settings_service import settings_service
from app.services.team_battle_manager import team_battle_manager
from app.ws.connection_manager import connection_manager

logger = logging.getLogger("team_combat")


class TeamCombatLoop:
    """Drives the continuous avatar-vs-avatar fighting in team PvP mode.

    One asyncio task per session, started when an arena connects and
    stopped when the last one disconnects -- an unwatched battle shouldn't
    burn CPU. Each tick resolves a bounded batch of attacks and broadcasts
    a single compact message the arena animates, rather than one message
    per shot.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def is_running(self, session_id: str) -> bool:
        task = self._tasks.get(session_id)
        return task is not None and not task.done()

    async def start(self, session_id: str) -> None:
        if self.is_running(session_id):
            return
        self._tasks[session_id] = asyncio.create_task(self._run(session_id))
        logger.info("team combat loop started for session=%s", session_id)

    async def stop(self, session_id: str) -> None:
        task = self._tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
            logger.info("team combat loop stopped for session=%s", session_id)

    async def _run(self, session_id: str) -> None:
        try:
            while True:
                delay = await self._tick(session_id)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("team combat loop crashed for session=%s", session_id)
        finally:
            self._tasks.pop(session_id, None)

    async def _tick(self, session_id: str) -> float:
        async with AsyncSessionLocal() as db:
            config = await settings_service.get(db, "team_battle")
            delay = float(config.get("tick_seconds", 2)) or 2.0

            session = await db.get(BattleSession, session_id)
            if session is None or session.status == "finished":
                return delay

            players = await team_battle_manager.alive_players(db, session_id)
            matchups = team_battle_manager.pick_matchups(players, config)
            if not matchups:
                return delay

            attacks = [
                team_battle_manager.resolve_attack(attacker, target, config)
                for attacker, target in matchups
            ]

            totals = team_battle_manager.team_totals(players)
            winner = team_battle_manager.winner_from(totals)
            if winner:
                session.status = "finished"
                session.winner_side = winner
                session.finished_at = datetime.now(timezone.utc)

            await db.commit()

            message = {
                "type": "pvp_combat",
                "session_id": session_id,
                "attacks": [
                    {
                        "attacker_user_id": a.attacker_user_id,
                        "target_user_id": a.target_user_id,
                        "damage": round(a.damage, 1),
                        "target_power": round(a.target_power, 1),
                        "eliminated": a.target_eliminated,
                    }
                    for a in attacks
                ],
                "teams": totals,
                "winner_side": winner,
            }

        await connection_manager.broadcast(session_id, message)

        if winner:
            await self.stop(session_id)

        return delay

    async def maybe_start_for_session(self, session_id: str) -> None:
        """Starts the loop only if this session's battle is in PvP mode."""
        async with AsyncSessionLocal() as db:
            session = await db.get(BattleSession, session_id)
            if session is None or session.status == "finished":
                return
            battle = await db.get(Battle, session.battle_id)
            if battle is None or battle.mode != "team_pvp":
                return
        await self.start(session_id)


team_combat_loop = TeamCombatLoop()
