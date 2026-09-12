import random
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Gift, Player


@dataclass
class TankShot:
    """One cannon shot: the firing side, and every enemy soldier it took out
    or wounded on the way."""

    team: str
    target_side: str
    total_damage: float
    hits: list[dict[str, Any]] = field(default_factory=list)

    @property
    def kills(self) -> int:
        return sum(1 for h in self.hits if h["eliminated"])


class TankWarManager:
    """Rules for tank war mode: the two characters are the gunners and the
    viewers are the troops.

    A gift makes the sender's tank fire, and the gift's coin price is the
    shot's power -- a 1-coin rose chips a single soldier, an expensive gift
    wipes out a whole squad. Enemies are picked at random, explode, and leave
    the arena.
    """

    @staticmethod
    def soldier_hp(config: dict[str, Any]) -> float:
        return float(config.get("soldier_hp", 100))

    @staticmethod
    def team_for_comment(text: str, config: dict[str, Any]) -> str | None:
        """Viewers pick a side by typing a keyword in chat (default "P" and
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
    def shot_damage(gift: Gift, quantity: int, config: dict[str, Any]) -> float:
        per_coin = float(config.get("damage_per_coin", 20))
        coins = max(1, gift.coins or 1)
        return coins * quantity * per_coin * (gift.multiplier or 1.0)

    @classmethod
    async def enemy_soldiers(cls, db: AsyncSession, session_id: str, team: str) -> list[Player]:
        enemy_team = "B" if team == "A" else "A"
        return (
            (
                await db.execute(
                    select(Player).where(
                        Player.session_id == session_id,
                        Player.team == enemy_team,
                        Player.eliminated.is_(False),
                        Player.power > 0,
                    )
                )
            )
            .scalars()
            .all()
        )

    @classmethod
    def resolve_shot(
        cls,
        team: str,
        enemies: list[Player],
        damage: float,
        config: dict[str, Any],
    ) -> TankShot:
        """Spends the shot's damage across randomly chosen enemies: it rolls
        onto the next soldier once the current one is destroyed, so power
        translates directly into body count."""
        shot = TankShot(team=team, target_side="B" if team == "A" else "A", total_damage=damage)
        if not enemies or damage <= 0:
            return shot

        max_targets = int(config.get("max_targets_per_shot", 10))
        pool = random.sample(enemies, min(len(enemies), max_targets))

        remaining = damage
        for target in pool:
            if remaining <= 0:
                break
            dealt = min(remaining, target.power)
            target.power = max(0.0, target.power - dealt)
            remaining -= dealt

            eliminated = target.power <= 0
            if eliminated:
                target.eliminated = True

            shot.hits.append(
                {
                    "user_id": target.user_id,
                    "username": target.username,
                    "damage": round(dealt, 1),
                    "power": round(target.power, 1),
                    "eliminated": eliminated,
                }
            )

        return shot

    @staticmethod
    def army_totals(players: list[Player]) -> dict[str, dict[str, float]]:
        totals = {"A": {"alive": 0, "recruited": 0}, "B": {"alive": 0, "recruited": 0}}
        for p in players:
            side = totals.get(p.team)
            if side is None:
                continue
            side["recruited"] += 1
            if not p.eliminated and p.power > 0:
                side["alive"] += 1
        return totals

    @staticmethod
    def winner_from(totals: dict[str, dict[str, float]]) -> str | None:
        a, b = totals["A"], totals["B"]
        if a["recruited"] and b["recruited"]:
            if a["alive"] == 0 and b["alive"] > 0:
                return "B"
            if b["alive"] == 0 and a["alive"] > 0:
                return "A"
        return None


tank_war_manager = TankWarManager()
