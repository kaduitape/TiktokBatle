from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Setting

DEFAULTS: dict[str, dict[str, Any]] = {
    "audio_mixer": {
        "music": 30,
        "shots": 80,
        "explosions": 80,
        "alerts": 70,
        "ui": 50,
        "victory": 80,
    },
    # Team PvP tuning -- every number the mode fights by lives here instead of
    # in game code, so the admin can rebalance a live match without a deploy.
    "team_battle": {
        "starting_power": 100,
        "power_per_gift_value": 10,
        "tick_seconds": 2,
        "attackers_per_tick": 40,
        "attack_base_damage": 4,
        "attack_power_scaling": 0.004,
        "level_up_every": 500,
        "elimination_enabled": True,
        "respawn_power": 0,
    },
    # Tank war tuning. The team keywords are settings rather than constants so
    # the mode isn't tied to any particular pair of characters -- swap them for
    # whatever the two sides are called on the day.
    # Tank war: the viewers chip at the enemy boss's huge health pool, and the
    # bosses bomb individual viewers back. Balance target with a 1.5M boss: a
    # 1-coin rose does 500, a 30-coin gift 15k, a 500-coin gift 250k -- so the
    # boss falls to sustained team effort, not to one whale.
    "tank_war": {
        "team_a_keyword": "A",
        "team_b_keyword": "B",
        # Fighters on the field at once, both sides together. Past this the
        # next arrivals wait in line and walk in as others are eliminated.
        "max_field_players": 100,
        "soldier_hp": 150,
        "boss_damage_per_coin": 500,
        # How often each boss lobs a bomb at the other side, and how hard it
        # hits. Default wipes a full-health soldier in one go.
        "bomb_interval_seconds": 12,
        "bomb_damage": 150,
        # The bomb picks from the most recently active enemies, so the people
        # actually playing are the ones getting hit.
        "bomb_active_pool": 10,
    },
}


class SettingsService:
    """Reads the Settings KV table with defaults merged in, cached so the
    PvP combat tick doesn't hit the DB every couple of seconds. Admin
    writes invalidate the cache so a rebalance applies on the next tick."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}

    async def get(self, db: AsyncSession, key: str) -> dict[str, Any]:
        if key in self._cache:
            return self._cache[key]

        defaults = DEFAULTS.get(key, {})
        row = await db.get(Setting, key)
        value = {**defaults, **(row.value or {})} if row else dict(defaults)
        self._cache[key] = value
        return value

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)


settings_service = SettingsService()
