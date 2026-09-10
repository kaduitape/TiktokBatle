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
    xp_max: int = 100_000


class CharacterOut(CharacterIn):
    id: str

    class Config:
        from_attributes = True


class BattleIn(BaseModel):
    name: str
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


class GiftIn(BaseModel):
    gift_key: str
    name: str
    icon: str = "🎁"
    image_url: str | None = None
    action_type: Literal["shot", "missile", "heal", "super_heal", "special"]
    value: float = 0
    target_side: Literal["A", "B"] = "A"
    animation_key: str = "shot"
    sound_key: str = "shot"
    combo_allowed: bool = True
    multiplier: float = 1.0
    active: bool = True


class GiftOut(GiftIn):
    id: str

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


class SessionOut(BaseModel):
    id: str
    battle_id: str
    side_a_xp: float
    side_b_xp: float
    status: str
    winner_side: str | None = None

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
    score: float
