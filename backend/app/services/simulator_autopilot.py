"""A paced, lifelike source of simulator events.

It intentionally emits through :mod:`simulation_provider`, never by writing
players or battle events itself.  The queue and GamePipeline therefore treat a
simulated viewer exactly as they treat a TikTok viewer.
"""
import asyncio
import random
from dataclasses import dataclass, field

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import Battle, BattleGift, BattleSession, Gift, Player, SimulatorProfile
from app.providers.simulation_provider import simulation_provider
from app.services.settings_service import settings_service


@dataclass(frozen=True)
class SimulatedIdentity:
    profile_id: str
    name: str
    avatar_url: str
    team: str

    @property
    def user_id(self) -> str:
        # The database ID, rather than the display name, is the durable
        # identity. Renaming a profile cannot make the same person enter again.
        return f"sim-profile-{self.profile_id}"


@dataclass
class ActiveSimulation:
    task: asyncio.Task[None] | None = None
    pending: list[SimulatedIdentity] = field(default_factory=list)
    viewers: list[SimulatedIdentity] = field(default_factory=list)
    team_a_limit: int = 0
    team_b_limit: int = 0
    team_a_joined: int = 0
    team_b_joined: int = 0
    shortfall: int = 0


def _team_slots(team_a_count: int, team_b_count: int) -> list[str]:
    """Interleave the two quotas so a small profile pool stays balanced."""
    slots: list[str] = []
    remaining_a, remaining_b = max(0, team_a_count), max(0, team_b_count)
    while remaining_a or remaining_b:
        if remaining_a:
            slots.append("A")
            remaining_a -= 1
        if remaining_b:
            slots.append("B")
            remaining_b -= 1
    return slots


class SimulatorAutopilot:
    """Runs at a human-looking cadence (join, pause, occasional gift).

    A run belongs to one session and is memory-only on purpose: pressing
    "stop" or restarting the server immediately stops artificial activity,
    which is the safe behaviour for a live control panel.
    """

    def __init__(self) -> None:
        self._runs: dict[str, ActiveSimulation] = {}

    def is_running(self, session_id: str) -> bool:
        run = self._runs.get(session_id)
        return bool(run and run.task and not run.task.done())

    def status(self, session_id: str) -> dict:
        run = self._runs.get(session_id)
        if not run:
            return {"session_id": session_id, "running": False}
        return {
            "session_id": session_id,
            "running": bool(run.task and not run.task.done()),
            "team_a_limit": run.team_a_limit,
            "team_b_limit": run.team_b_limit,
            "team_a_joined": run.team_a_joined,
            "team_b_joined": run.team_b_joined,
            "pending": len(run.pending),
            "profiles_exhausted": not run.pending and run.shortfall > 0,
            "shortfall": run.shortfall,
        }

    async def start(
        self,
        session_id: str,
        profiles: list[SimulatorProfile],
        team_a_count: int,
        team_b_count: int,
    ) -> dict:
        await self.stop(session_id)
        limits = {"A": max(0, team_a_count), "B": max(0, team_b_count)}
        profile_by_user_id = {f"sim-profile-{profile.id}": profile for profile in profiles}

        existing: list[Player] = []
        if profile_by_user_id:
            async with AsyncSessionLocal() as db:
                existing = list(
                    (
                        await db.execute(
                            select(Player).where(
                                Player.session_id == session_id,
                                Player.user_id.in_(list(profile_by_user_id)),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

        # Every stored player consumes its profile forever for this arena,
        # including eliminated players. This is the cross-team uniqueness
        # rule: stopping/starting the simulator cannot move the same face to
        # the adversary or make it enter twice.
        used_user_ids = {player.user_id for player in existing}
        joined = {
            side: sum(1 for player in existing if player.team == side)
            for side in ("A", "B")
        }
        available = [
            profile
            for profile in profiles
            if f"sim-profile-{profile.id}" not in used_user_ids
        ]
        random.shuffle(available)
        slots = _team_slots(
            max(0, limits["A"] - joined["A"]),
            max(0, limits["B"] - joined["B"]),
        )
        pending = [
            SimulatedIdentity(
                profile_id=profile.id,
                name=profile.name,
                avatar_url=profile.avatar_url,
                team=team,
            )
            for profile, team in zip(available, slots)
        ]
        active_existing = [
            SimulatedIdentity(
                profile_id=profile_by_user_id[player.user_id].id,
                name=profile_by_user_id[player.user_id].name,
                avatar_url=profile_by_user_id[player.user_id].avatar_url,
                team=player.team,
            )
            for player in existing
            if not player.eliminated and player.team in ("A", "B")
        ]
        run = ActiveSimulation(
            pending=pending,
            viewers=active_existing,
            team_a_limit=limits["A"],
            team_b_limit=limits["B"],
            team_a_joined=joined["A"],
            team_b_joined=joined["B"],
            shortfall=max(0, len(slots) - len(available)),
        )
        self._runs[session_id] = run
        run.task = asyncio.create_task(self._run(session_id))
        return self.status(session_id)

    async def stop(self, session_id: str) -> None:
        run = self._runs.pop(session_id, None)
        if not run or not run.task or run.task.done():
            return
        run.task.cancel()
        try:
            await run.task
        except asyncio.CancelledError:
            pass

    async def _context(self, session_id: str) -> tuple[str, list[str], str, str] | None:
        """Return mode, valid gifts and current tank join words for a session."""
        async with AsyncSessionLocal() as db:
            session = await db.get(BattleSession, session_id)
            if session is None or session.status == "finished":
                return None
            battle = await db.get(Battle, session.battle_id)
            if battle is None:
                return None

            selected_ids = (
                await db.execute(select(BattleGift.gift_id).where(BattleGift.battle_id == battle.id))
            ).scalars().all()
            gift_query = select(Gift.gift_key).where(Gift.active.is_(True))
            if selected_ids:
                gift_query = gift_query.where(Gift.id.in_(selected_ids))
            gifts = list((await db.execute(gift_query)).scalars().all())
            tank = await settings_service.get(db, "tank_war")
            return (
                battle.mode,
                gifts,
                str(tank.get("team_a_keyword", "A")),
                str(tank.get("team_b_keyword", "B")),
            )

    async def _add_viewer(
        self,
        session_id: str,
        run: ActiveSimulation,
        mode: str,
        team_a_word: str,
        team_b_word: str,
    ) -> SimulatedIdentity:
        viewer = run.pending.pop(0)
        run.viewers.append(viewer)
        if viewer.team == "A":
            run.team_a_joined += 1
        else:
            run.team_b_joined += 1
        await simulation_provider.simulate_join(
            session_id=session_id,
            user_id=viewer.user_id,
            username=viewer.name,
            nickname=viewer.name,
            avatar_url=viewer.avatar_url,
            team=viewer.team,
        )
        # Tank war correctly requires a side choice. The simulator performs
        # that visible chat action instead of bypassing the enlistment rule.
        if mode == "tank_war":
            await simulation_provider.simulate_comment(
                session_id=session_id,
                user_id=viewer.user_id,
                username=viewer.name,
                nickname=viewer.name,
                avatar_url=viewer.avatar_url,
                text=team_a_word if viewer.team == "A" else team_b_word,
            )
        return viewer

    async def _run(self, session_id: str) -> None:
        try:
            while True:
                context = await self._context(session_id)
                run = self._runs.get(session_id)
                if context is None or run is None:
                    return
                mode, gift_keys, team_a_word, team_b_word = context

                # Most ticks are an attack from a person already present; a
                # smaller portion is a new arrival. This reads much closer to
                # a live room than a uniform burst of anonymous events.
                if run.pending and (not run.viewers or random.random() < 0.30):
                    viewer = await self._add_viewer(
                        session_id, run, mode, team_a_word, team_b_word
                    )
                    # A new viewer sometimes watches for a beat before gifting.
                    send_gift = bool(gift_keys) and random.random() < 0.42
                elif run.viewers:
                    viewer = random.choice(run.viewers)
                    send_gift = bool(gift_keys) and random.random() < 0.78
                else:
                    # No selected profile remains and nobody from this run can
                    # attack. End cleanly instead of fabricating another user.
                    return

                if send_gift:
                    await simulation_provider.simulate_gift(
                        session_id=session_id,
                        user_id=viewer.user_id,
                        username=viewer.name,
                        nickname=viewer.name.removeprefix("sim_").replace("_", " "),
                        avatar_url=viewer.avatar_url,
                        gift_key=random.choice(gift_keys),
                        quantity=random.choices([1, 2, 3, 5], weights=[70, 16, 9, 5])[0],
                    )

                await asyncio.sleep(random.uniform(1.1, 3.4))
        except asyncio.CancelledError:
            raise
        finally:
            current = self._runs.get(session_id)
            if current and current.task is asyncio.current_task():
                self._runs.pop(session_id, None)


simulator_autopilot = SimulatorAutopilot()
