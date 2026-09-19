import random
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Gift, Player


@dataclass
class BombHit:
    """One boss bomb landing on a single enemy viewer."""

    user_id: str
    username: str
    damage: float
    power: float
    eliminated: bool


class TankWarManager:
    """Rules for tank war mode: the two characters are bosses with a huge
    health pool, and the viewers are the armies chipping at them.

    Both sides only ever attack the *enemy boss* -- viewers never shoot each
    other. The bosses answer back on their own schedule by lobbing a bomb at
    one active enemy viewer, which hurts enough to take a full-health soldier
    out. Every number comes from the `tank_war` settings key.
    """

    @staticmethod
    def soldier_hp(config: dict[str, Any]) -> float:
        return float(config.get("soldier_hp", 150))

    @staticmethod
    def team_for_comment(text: str, config: dict[str, Any]) -> str | None:
        """Viewers pick a side by typing a keyword in chat (default "A" and
        "B"). Matching is case-insensitive and ignores surrounding spaces, but
        requires the whole message to be the keyword so ordinary chatter
        doesn't enlist people by accident."""
        cleaned = (text or "").strip().lower()
        if not cleaned:
            return None
        if cleaned == str(config.get("team_a_keyword", "P")).strip().lower():
            return "A"
        if cleaned == str(config.get("team_b_keyword", "B")).strip().lower():
            return "B"
        return None

    @staticmethod
    def enemy_side(team: str) -> str:
        return "B" if team == "A" else "A"

    @staticmethod
    def field_capacity(config: dict[str, Any]) -> int:
        return max(1, int(config.get("max_field_players", 100)))

    @staticmethod
    async def count_on_field(db: AsyncSession, session_id: str) -> int:
        """Fighters actually standing in the arena, both sides together."""
        return (
            await db.execute(
                select(func.count())
                .select_from(Player)
                .where(
                    Player.session_id == session_id,
                    Player.team_selected.is_(True),
                    Player.queued.is_(False),
                    Player.eliminated.is_(False),
                    Player.power > 0,
                )
            )
        ).scalar_one()

    @staticmethod
    async def field_is_full(db: AsyncSession, session_id: str, config: dict[str, Any]) -> bool:
        return await TankWarManager.count_on_field(db, session_id) >= TankWarManager.field_capacity(config)

    @staticmethod
    async def next_in_queue(db: AsyncSession, session_id: str) -> Player | None:
        """First in, first on the field."""
        return (
            await db.execute(
                select(Player)
                .where(
                    Player.session_id == session_id,
                    Player.team_selected.is_(True),
                    Player.queued.is_(True),
                )
                .order_by(Player.created_at.asc())
                .limit(1)
            )
        ).scalars().first()

    @staticmethod
    async def queue_position(db: AsyncSession, session_id: str, player: Player) -> int:
        """Where somebody stands in line, 1-based, so the arena can tell them."""
        ahead = (
            await db.execute(
                select(func.count())
                .select_from(Player)
                .where(
                    Player.session_id == session_id,
                    Player.team_selected.is_(True),
                    Player.queued.is_(True),
                    Player.created_at < player.created_at,
                )
            )
        ).scalar_one()
        return int(ahead) + 1

    @staticmethod
    async def promote_from_queue(
        db: AsyncSession, session_id: str, config: dict[str, Any]
    ) -> Player | None:
        """Walks the next person in line onto the field, at full health.
        Called when a slot opens, i.e. when somebody is eliminated."""
        if await TankWarManager.field_is_full(db, session_id, config):
            return None
        player = await TankWarManager.next_in_queue(db, session_id)
        if not player:
            return None
        starting = TankWarManager.soldier_hp(config)
        player.queued = False
        player.eliminated = False
        player.power = starting
        player.peak_power = max(player.peak_power, starting)
        return player

    @staticmethod
    def boss_damage(gift: Gift, quantity: int, config: dict[str, Any]) -> float:
        """The gift's coin price is the shot's power, so an expensive gift
        moves the boss's bar far more than a cheap one."""
        per_coin = float(config.get("boss_damage_per_coin", 500))
        coins = max(1, gift.coins or 1)
        return coins * quantity * per_coin * (gift.multiplier or 1.0)

    @staticmethod
    async def pick_bomb_target(
        db: AsyncSession, session_id: str, team: str, config: dict[str, Any]
    ) -> Player | None:
        """Picks who eats the next bomb: a living soldier of `team`, drawn from
        the most recently active ones so the bomb lands on somebody who is
        actually playing rather than a viewer who enlisted and left."""
        pool_size = max(1, int(config.get("bomb_active_pool", 10)))
        candidates = (
            (
                await db.execute(
                    select(Player)
                    .where(
                        Player.session_id == session_id,
                        Player.team == team,
                        Player.team_selected.is_(True),
                        Player.queued.is_(False),
                        Player.eliminated.is_(False),
                        Player.power > 0,
                    )
                    .order_by(Player.last_interaction.desc())
                    .limit(pool_size)
                )
            )
            .scalars()
            .all()
        )
        return random.choice(candidates) if candidates else None

    @staticmethod
    def resolve_bomb(target: Player, config: dict[str, Any]) -> BombHit:
        damage = float(config.get("bomb_damage", 150))
        dealt = min(damage, target.power)
        target.power = max(0.0, target.power - dealt)

        eliminated = target.power <= 0
        if eliminated:
            target.eliminated = True

        return BombHit(
            user_id=target.user_id,
            username=target.username,
            damage=round(dealt, 1),
            power=round(target.power, 1),
            eliminated=eliminated,
        )

    @staticmethod
    def army_totals(players: list[Player]) -> dict[str, dict[str, float]]:
        totals = {
            "A": {"alive": 0, "recruited": 0, "queued": 0},
            "B": {"alive": 0, "recruited": 0, "queued": 0},
        }
        for p in players:
            if not p.team_selected:
                continue
            side = totals.get(p.team)
            if side is None:
                continue
            side["recruited"] += 1
            if p.queued:
                side["queued"] += 1
            elif not p.eliminated and p.power > 0:
                side["alive"] += 1
        return totals


tank_war_manager = TankWarManager()
