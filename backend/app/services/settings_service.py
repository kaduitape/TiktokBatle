from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Setting

DEFAULTS: dict[str, dict[str, Any]] = {
    # Layout of the 1080x1920 arena. The live overlay covers the bottom of the
    # screen -- on TikTok that is the chat -- and everything the arena anchors
    # to the bottom was landing under it. This strip is left empty so the
    # ground, the feed and the legend stop where the chat begins.
    "arena": {
        "bottom_safe_px": 420,
        # Overlay image drawn on top of the arena -- a legend, rules card or
        # watermark the admin draws themselves. Empty means nothing is drawn.
        # Position is a fraction of the arena (0-1) so it survives any scale.
        "legend_image_url": "",
        "legend_x": 0.5,
        "legend_y": 0.9,
        "legend_scale": 1.0,
    },
    # Automatic gift capture. Learning mode lets an operator run a private
    # LIVE, send gifts to discover their IDs, and have every one of them
    # recorded without any of it touching the scoreboard.
    "live_capture": {
        "learning_mode": False,
    },
    "audio_mixer": {
        "music": 30,
        "shots": 80,
        "explosions": 80,
        "alerts": 70,
        "ui": 50,
        "victory": 80,
    },
    # Social interactions are intentionally independent from gift prices.
    # TikTok can batch several taps in one LikeEvent, so the heal is per heart.
    "social_actions": {
        "heal_per_like": 100,
        "max_likes_per_event": 100,
        "follow_life_multiplier": 3,
        # Classic mode has no soldier HP to use as a starting point. This base
        # still gives its viewer avatar a concrete life value after following.
        "follow_base_life": 100,
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

    async def set(self, db: AsyncSession, key: str, value: dict[str, Any]) -> dict[str, Any]:
        """Write a settings key and drop it from the cache in one step, so a
        service flipping a switch cannot leave readers on a stale value."""
        row = await db.get(Setting, key)
        if row:
            row.value = value
        else:
            db.add(Setting(key=key, value=value))
        await db.flush()
        self.invalidate(key)
        return value

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)


settings_service = SettingsService()
