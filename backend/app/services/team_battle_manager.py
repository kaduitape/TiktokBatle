import random
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Player


@dataclass
class AttackResult:
    attacker_id: str
    attacker_user_id: str
    target_id: str
    target_user_id: str
    damage: float
    target_power: float
    target_eliminated: bool


@dataclass
class GrowthResult:
    player_id: str
    power: float
    level: int
    leveled_up: bool
    gained: float


class TeamBattleManager:
    """Rules for the team PvP mode: viewers are the fighters, each with its
    own power pool that doubles as health. Gifts grow the sender; combat
    ticks spend that power attacking the opposing team's avatars.

    Everything numeric comes from the `team_battle` settings key, so a live
    match can be rebalanced from the admin panel without a deploy.
    """

    @staticmethod
    def starting_power(config: dict[str, Any]) -> float:
        return float(config.get("starting_power", 100))

    @staticmethod
    def level_for(power: float, config: dict[str, Any]) -> int:
        step = float(config.get("level_up_every", 500)) or 500
        return max(1, int(power // step) + 1)

    @classmethod
    def grow(cls, player: Player, gift_value: float, quantity: int, config: dict[str, Any]) -> GrowthResult:
        """A gift feeds the sender's own fighter. Damage-type gifts (negative
        value) still grow the sender -- in PvP the gift's magnitude is how
        hard you hit, not who you hurt."""
        per_value = float(config.get("power_per_gift_value", 10))
        gained = abs(gift_value) * quantity * per_value

        before_level = player.level
        player.power = max(0.0, player.power + gained)
        player.peak_power = max(player.peak_power, player.power)
        player.level = cls.level_for(player.power, config)
        if player.eliminated and player.power > 0:
            player.eliminated = False

        return GrowthResult(
            player_id=player.id,
            power=player.power,
            level=player.level,
            leveled_up=player.level > before_level,
            gained=gained,
        )

    @staticmethod
    def attack_damage(attacker: Player, config: dict[str, Any]) -> float:
        base = float(config.get("attack_base_damage", 4))
        scaling = float(config.get("attack_power_scaling", 0.004))
        return base + attacker.power * scaling

    @classmethod
    def resolve_attack(
        cls,
        attacker: Player,
        target: Player,
        config: dict[str, Any],
        damage_override: float | None = None,
    ) -> AttackResult:
        """`damage_override` is how a gift-powered strike hits harder than a
        routine combat tick -- the gift's own magnitude becomes the punch."""
        damage = cls.attack_damage(attacker, config) if damage_override is None else damage_override
        target.power = max(0.0, target.power - damage)

        eliminated = False
        if target.power <= 0 and config.get("elimination_enabled", True):
            respawn = float(config.get("respawn_power", 0))
            if respawn > 0:
                target.power = respawn
            else:
                target.eliminated = True
                eliminated = True
                attacker.kills += 1

        attacker.damage_total += damage

        return AttackResult(
            attacker_id=attacker.id,
            attacker_user_id=attacker.user_id,
            target_id=target.id,
            target_user_id=target.user_id,
            damage=damage,
            target_power=target.power,
            target_eliminated=eliminated,
        )

    @staticmethod
    async def assign_balanced_team(db: AsyncSession, session_id: str) -> str:
        """PvP is only fun if both sides have fighters, so a viewer who joins
        without picking a side lands on whichever team is currently smaller
        (random tiebreak) instead of a coin flip that can stack one side."""
        rows = (
            await db.execute(
                select(Player.team).where(Player.session_id == session_id, Player.eliminated.is_(False))
            )
        ).scalars().all()
        count_a = sum(1 for t in rows if t == "A")
        count_b = sum(1 for t in rows if t == "B")
        if count_a == count_b:
            return random.choice(["A", "B"])
        return "A" if count_a < count_b else "B"

    @staticmethod
    async def alive_players(db: AsyncSession, session_id: str) -> list[Player]:
        return (
            (
                await db.execute(
                    select(Player).where(
                        Player.session_id == session_id,
                        Player.eliminated.is_(False),
                        Player.power > 0,
                    )
                )
            )
            .scalars()
            .all()
        )

    @classmethod
    def pick_matchups(
        cls, players: list[Player], config: dict[str, Any]
    ) -> list[tuple[Player, Player]]:
        """Samples a bounded number of attackers per tick so a 1000-viewer
        arena stays O(attackers_per_tick) instead of O(players squared)."""
        team_a = [p for p in players if p.team == "A"]
        team_b = [p for p in players if p.team == "B"]
        if not team_a or not team_b:
            return []

        limit = int(config.get("attackers_per_tick", 40))
        attackers = players if len(players) <= limit else random.sample(players, limit)

        matchups: list[tuple[Player, Player]] = []
        for attacker in attackers:
            enemies = team_b if attacker.team == "A" else team_a
            if enemies:
                matchups.append((attacker, random.choice(enemies)))
        return matchups

    @staticmethod
    def team_totals(players: list[Player]) -> dict[str, dict[str, float]]:
        totals = {
            "A": {"power": 0.0, "alive": 0, "fighters": 0},
            "B": {"power": 0.0, "alive": 0, "fighters": 0},
        }
        for p in players:
            side = totals.get(p.team)
            if side is None:
                continue
            side["fighters"] += 1
            if not p.eliminated and p.power > 0:
                side["power"] += p.power
                side["alive"] += 1
        return totals

    @staticmethod
    def winner_from(totals: dict[str, dict[str, float]]) -> str | None:
        """A team only loses once it actually had fighters and lost all of
        them -- an empty arena isn't a victory."""
        a, b = totals["A"], totals["B"]
        if a["fighters"] and b["fighters"]:
            if a["alive"] == 0 and b["alive"] > 0:
                return "B"
            if b["alive"] == 0 and a["alive"] > 0:
                return "A"
        return None


team_battle_manager = TeamBattleManager()
