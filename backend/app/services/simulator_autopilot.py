"""A paced, lifelike source of simulator events.

It intentionally emits through :mod:`simulation_provider`, never by writing
players or battle events itself.  The queue and GamePipeline therefore treat a
simulated viewer exactly as they treat a TikTok viewer.
"""
import asyncio
import random
import re
from dataclasses import dataclass, field

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import Battle, BattleGift, BattleSession, Gift, SimulatorProfile
from app.providers.simulation_provider import simulation_provider
from app.services.settings_service import settings_service


@dataclass(frozen=True)
class SimulatedIdentity:
    name: str
    avatar_url: str


@dataclass
class ActiveSimulation:
    task: asyncio.Task[None]
    profiles: list[SimulatedIdentity]
    viewers: list[SimulatedIdentity] = field(default_factory=list)
    next_viewer: int = 1


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
        return bool(run and not run.task.done())

    async def start(self, session_id: str, profiles: list[SimulatorProfile]) -> None:
        await self.stop(session_id)
        identities = [
            SimulatedIdentity(name=profile.name, avatar_url=profile.avatar_url)
            for profile in profiles
        ]
        # A saved face is optional. The fallback lets a brand-new install
        # verify the simulator immediately, while the panel makes it clear
        # which faces are being used once profiles are registered.
        if not identities:
            identities = [
                SimulatedIdentity(
                    name="espectador",
                    avatar_url="https://i.pravatar.cc/160?u=simulator-default",
                )
            ]

        task = asyncio.create_task(self._run(session_id))
        self._runs[session_id] = ActiveSimulation(task=task, profiles=identities)

    async def stop(self, session_id: str) -> None:
        run = self._runs.pop(session_id, None)
        if not run or run.task.done():
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

    @staticmethod
    def _username(seed: str, number: int) -> str:
        # User IDs derive from this value. Keep it readable in the arena and
        # stable enough to avoid exotic URL/file-name characters from labels.
        cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", seed.strip()).strip("_") or "viewer"
        return f"sim_{cleaned[:32]}_{number}"

    async def _add_viewer(
        self,
        session_id: str,
        run: ActiveSimulation,
        mode: str,
        team_a_word: str,
        team_b_word: str,
    ) -> SimulatedIdentity:
        base = random.choice(run.profiles)
        viewer = SimulatedIdentity(
            name=self._username(base.name, run.next_viewer),
            avatar_url=base.avatar_url,
        )
        run.next_viewer += 1
        run.viewers.append(viewer)
        await simulation_provider.simulate_join(
            session_id=session_id,
            user_id=f"sim-{viewer.name}",
            username=viewer.name,
            nickname=base.name,
            avatar_url=viewer.avatar_url,
        )
        # Tank war correctly requires a side choice. The simulator performs
        # that visible chat action instead of bypassing the enlistment rule.
        if mode == "tank_war":
            await simulation_provider.simulate_comment(
                session_id=session_id,
                user_id=f"sim-{viewer.name}",
                username=viewer.name,
                nickname=base.name,
                avatar_url=viewer.avatar_url,
                text=random.choice([team_a_word, team_b_word]),
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
                if not run.viewers or (len(run.viewers) < 24 and random.random() < 0.30):
                    viewer = await self._add_viewer(
                        session_id, run, mode, team_a_word, team_b_word
                    )
                    # A new viewer sometimes watches for a beat before gifting.
                    send_gift = bool(gift_keys) and random.random() < 0.42
                else:
                    viewer = random.choice(run.viewers)
                    send_gift = bool(gift_keys) and random.random() < 0.78

                if send_gift:
                    await simulation_provider.simulate_gift(
                        session_id=session_id,
                        user_id=f"sim-{viewer.name}",
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
