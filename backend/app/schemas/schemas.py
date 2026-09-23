from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Standard normalized live event (section 48 of the spec). Every provider
# (TikTok, Simulator, future platforms) must emit exactly this shape so the
# rest of the pipeline never needs to know where an event came from.
# ---------------------------------------------------------------------------


class LiveUser(BaseModel):
    id: str
    username: str
    nickname: str | None = None
    avatar: str | None = None


class LiveGift(BaseModel):
    id: str
    name: str
    quantity: int = 1


class LiveEvent(BaseModel):
    type: Literal["gift_received", "viewer_join", "like", "follow", "comment"]
    user: LiveUser
    gift: LiveGift | None = None
    comment: str | None = None
    timestamp: float = 0
    raw: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# REST/admin schemas
# ---------------------------------------------------------------------------


class CharacterIn(BaseModel):
    name: str
    image_url: str | None = None
    background_url: str | None = None
    team_color: str = "#3498db"
    scale: float = 1.0
    pos_x: float = 0.5
    pos_y: float = 0.5
    flip_h: bool = False
    shadow: bool = True
    outline: bool = False
    glow: bool = False
    idle_animation: str = "idle"
    hit_animation: str = "hit"
    heal_animation: str = "heal"
    sprite_columns: int = 0
    sprite_rows: int = 1
    sprite_frame_count: int = 0
    sprite_fps: int = 10
    #: Rows of the sheet, named. See Character.sprite_clips.
    sprite_clips: list[dict[str, Any]] = Field(default_factory=list)
    hit_image_url: str | None = None
    fire_image_url: str | None = None
    xp_max: int = 100_000


class CharacterOut(CharacterIn):
    id: str

    class Config:
        from_attributes = True


class BattleGiftsIn(BaseModel):
    """Empty list = the battle accepts every active gift."""

    gift_ids: list[str] = Field(default_factory=list)


class BattleIn(BaseModel):
    name: str
    mode: Literal["character", "team_pvp", "tank_war"] = "character"
    side_a_character_id: str
    side_b_character_id: str
    background_url: str | None = None
    max_players: int = 500
    one_ball_per_user: bool = True
    battle_time_seconds: int | None = None
    sudden_death_enabled: bool = False
    sudden_death_multiplier: float = 2.0
    auto_restart: bool = False
    is_template: bool = False
    template_name: str | None = None


class BattleOut(BattleIn):
    id: str

    class Config:
        from_attributes = True


#: Kept in sync with gift_rule_engine.ACTION_OPTIONS / TARGET_OPTIONS.
GiftAction = Literal[
    "shot",
    "burst",
    "missile",
    "bomb",
    "meteor",
    "airstrike",
    "lightning",
    "heal",
    "super_heal",
    "shield",
    "special",
    "none",
]
GiftTarget = Literal["A", "B", "own_team", "enemy_team", "both", "global"]


class GiftIn(BaseModel):
    gift_key: str
    platform: str = "tiktok"
    tiktok_gift_id: str | None = None
    name: str
    icon: str = "🎁"
    image_url: str | None = None
    action_type: GiftAction
    value: float = 0
    target_side: GiftTarget = "A"
    coins: int = 1
    animation_key: str = "shot"
    sound_key: str = "shot"
    combo_allowed: bool = True
    multiplier: float = 1.0
    active: bool = True


class GiftOut(GiftIn):
    id: str

    class Config:
        from_attributes = True


class LiveGiftOut(BaseModel):
    """One row of the automatic catalogue, as the admin panel sees it.

    Every field the platform did not supply comes back as null rather than as
    a stand-in value, so "valor desconhecido" stays distinguishable from
    "valor zero".
    """

    id: str
    platform: str
    platform_gift_id: str
    name: str | None = None
    image_url: str | None = None
    diamond_value: int | None = None
    coin_value: int | None = None
    times_received: int
    first_seen_at: datetime
    last_seen_at: datetime
    active: bool
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    # The rule attached to this gift, if somebody configured one.
    configured: bool = False
    gift_id: str | None = None
    gift_key: str | None = None
    action_type: str | None = None
    action_label: str | None = None
    xp_value: float | None = None
    target_side: str | None = None
    animation_key: str | None = None
    sound_key: str | None = None


class LiveGiftRuleIn(BaseModel):
    """What the "Configurar presente" modal saves.

    Only the action matters here -- the gift's identity comes from the
    catalogue row, never from anything typed in.
    """

    action_type: GiftAction
    target_side: GiftTarget = "A"
    value: float = 0
    animation_key: str = "shot"
    sound_key: str = "shot"
    coins: int | None = None
    multiplier: float = 1.0
    combo_allowed: bool = True
    active: bool = True
    icon: str | None = None


class LearningModeIn(BaseModel):
    enabled: bool


class SpriteModelIn(BaseModel):
    """A generated character saved for reuse. Art only -- nothing about where
    a fighter stands or how much health it has belongs here."""

    name: str
    image_url: str | None = None
    sprite_columns: int = 0
    sprite_rows: int = 1
    sprite_frame_count: int = 0
    sprite_fps: int = 10
    hit_image_url: str | None = None
    fire_image_url: str | None = None
    #: Which row of the sheet is which movement. See Character.sprite_clips.
    sprite_clips: list[dict[str, Any]] = Field(default_factory=list)
    description: str | None = None
    poses: list[str] = Field(default_factory=list)


class SpriteModelOut(BaseModel):
    id: str
    name: str
    image_url: str | None = None
    sprite_columns: int
    sprite_rows: int
    sprite_frame_count: int
    sprite_fps: int
    hit_image_url: str | None = None
    fire_image_url: str | None = None
    sprite_clips: list[dict[str, Any]] = Field(default_factory=list)
    description: str | None = None
    poses: list[str] = Field(default_factory=list)
    created_at: datetime

    class Config:
        from_attributes = True


class ComboTierIn(BaseModel):
    threshold: int
    label: str
    animation_key: str
    damage_multiplier: float = 1.0


class ComboTierOut(ComboTierIn):
    id: str

    class Config:
        from_attributes = True


class SimulateGiftRequest(BaseModel):
    session_id: str
    username: str
    nickname: str | None = None
    avatar_url: str | None = None
    gift_key: str
    quantity: int = 1
    team: Literal["A", "B"] | None = None


class SimulatorProfileIn(BaseModel):
    """A reusable face used by the live-event simulator."""

    name: str = Field(min_length=1, max_length=80)
    avatar_url: str = Field(min_length=1, max_length=2048)


class SimulatorProfileOut(SimulatorProfileIn):
    id: str

    class Config:
        from_attributes = True


class SimulatorAutoStartIn(BaseModel):
    session_id: str
    # Empty means every saved simulator profile. This keeps the usual case
    # simple while still allowing a presenter to test just selected faces.
    profile_ids: list[str] = Field(default_factory=list)


class BattleBackgroundIn(BaseModel):
    """The single image which fills an arena behind both teams."""

    background_url: str | None = None


class SessionOut(BaseModel):
    id: str
    battle_id: str
    side_a_xp: float
    side_b_xp: float
    status: str
    winner_side: str | None = None

    class Config:
        from_attributes = True


class ActiveBattleOut(BaseModel):
    """The battle session currently receiving live/simulated events."""

    battle: BattleOut
    session: SessionOut


class MusicTrackIn(BaseModel):
    name: str
    file_url: str
    category: Literal["normal", "danger", "victory", "defeat"] = "normal"
    order_index: int = 0


class MusicTrackOut(MusicTrackIn):
    id: str

    class Config:
        from_attributes = True


class RankingEntry(BaseModel):
    user_id: str
    username: str
    nickname: str | None
    avatar_url: str | None
    team: str
    damage_total: float
    heal_total: float
    gifts_total: int
    combo_count: int
    power: float = 0
    kills: int = 0
    score: float


class PvpPlayerOut(BaseModel):
    """A single fighter in team PvP mode."""

    id: str
    user_id: str
    username: str
    nickname: str | None
    avatar_url: str | None
    team: str
    power: float
    level: int
    kills: int
    eliminated: bool

    class Config:
        from_attributes = True
