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
