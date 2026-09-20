import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def gen_id() -> str:
    return uuid.uuid4().hex


class Character(Base):
    """A reusable, fully admin-configurable fighter. Nothing about a
    specific character (name/art/animations) is hardcoded anywhere else --
    a Battle just points at two of these."""

    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    background_url: Mapped[str | None] = mapped_column(String, nullable=True)
    team_color: Mapped[str] = mapped_column(String, default="#3498db")

    scale: Mapped[float] = mapped_column(Float, default=1.0)
    pos_x: Mapped[float] = mapped_column(Float, default=0.5)
    pos_y: Mapped[float] = mapped_column(Float, default=0.5)
    flip_h: Mapped[bool] = mapped_column(Boolean, default=False)

    shadow: Mapped[bool] = mapped_column(Boolean, default=True)
    outline: Mapped[bool] = mapped_column(Boolean, default=False)
    glow: Mapped[bool] = mapped_column(Boolean, default=False)

    idle_animation: Mapped[str] = mapped_column(String, default="idle")
    hit_animation: Mapped[str] = mapped_column(String, default="hit")
    heal_animation: Mapped[str] = mapped_column(String, default="heal")

    # Sprite sheet: one uploaded image holding the poses side by side. The grid
    # is described in columns/rows rather than pixels so the admin never has to
    # measure anything -- the frame size is the image size divided by the grid.
    # sprite_columns = 0 means the upload is a plain, still image.
    sprite_columns: Mapped[int] = mapped_column(Integer, default=0)
    sprite_rows: Mapped[int] = mapped_column(Integer, default=1)
    # 0 = every cell in the grid. Set it when the last cells are left blank.
    sprite_frame_count: Mapped[int] = mapped_column(Integer, default=0)
    sprite_fps: Mapped[int] = mapped_column(Integer, default=10)

    # Reaction art: single stills swapped in for a moment when the character
    # does something. Optional -- without them the character just keeps its
    # idle art and the existing shake/tint still plays.
    hit_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    fire_image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    xp_max: Mapped[int] = mapped_column(Integer, default=100_000)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSecret(Base):
    """Credentials pasted into the admin panel.

    Deliberately NOT the `settings` table: GET /api/settings/{key} is public
    (the arena reads game balance from it without logging in), so anything
    stored there is readable by anyone who can reach the server. These rows are
    only ever reachable through admin-authenticated endpoints, and are never
    returned in full -- callers get a masked preview.

    The value is stored as written. The app has no key management of its own,
    so treat a database dump or backup as carrying the credential.
    """

    __tablename__ = "app_secrets"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Battle(Base):
    """A configurable template: 'Side A vs Side B'. Admin picks which
    Character fills each side -- no side is ever tied to a specific name."""

    __tablename__ = "battles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    name: Mapped[str] = mapped_column(String, nullable=False)

    # "character": viewers attack the two configured characters (original mode).
    # "team_pvp": viewers themselves are the fighters -- team A's avatars shoot
    # team B's avatars, each one growing and dying on its own.
    mode: Mapped[str] = mapped_column(String, default="character")

    side_a_character_id: Mapped[str] = mapped_column(ForeignKey("characters.id"))
    side_b_character_id: Mapped[str] = mapped_column(ForeignKey("characters.id"))

    background_url: Mapped[str | None] = mapped_column(String, nullable=True)

    max_players: Mapped[int] = mapped_column(Integer, default=500)
    one_ball_per_user: Mapped[bool] = mapped_column(Boolean, default=True)

    battle_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sudden_death_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sudden_death_multiplier: Mapped[float] = mapped_column(Float, default=2.0)

    auto_restart: Mapped[bool] = mapped_column(Boolean, default=False)

    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    template_name: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    side_a = relationship("Character", foreign_keys=[side_a_character_id])
    side_b = relationship("Character", foreign_keys=[side_b_character_id])


class SimulatorProfile(Base):
    """A saved person/photo the simulator can send through the live pipeline.

    These are deliberately separate from real ``Player`` records: a profile is
    just reusable input for a future simulated viewer, not somebody who has
    participated in a particular battle yet.
    """

    __tablename__ = "simulator_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    avatar_url: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BattleGift(Base):
    """Which gifts a battle accepts.

    No rows for a battle means "every active gift", so battles created before
    this keep working untouched. Once a battle has rows, gifts outside the list
    are ignored by the pipeline -- a viewer can still send them, they just do
    nothing in that battle.
    """

    __tablename__ = "battle_gifts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battles.id"))
    gift_id: Mapped[str] = mapped_column(ForeignKey("gifts.id"))


class BattleSession(Base):
    """One live run of a Battle: current XP, status, timers."""

    __tablename__ = "battle_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battles.id"))

    side_a_xp: Mapped[float] = mapped_column(Float, default=100_000)
    side_b_xp: Mapped[float] = mapped_column(Float, default=100_000)

    status: Mapped[str] = mapped_column(String, default="active")  # active|sudden_death|finished
    winner_side: Mapped[str | None] = mapped_column(String, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    battle = relationship("Battle")


class Gift(Base):
    """Everything about a gift is admin-editable -- key/icon/action/value/
    target/animation/sound/combo behaviour -- so no gift is ever hardcoded
    into game logic. The seed data just pre-populates sensible defaults."""

    __tablename__ = "gifts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    gift_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # Stable ID emitted by TikTok for this gift. It is intentionally separate
    # from gift_key: the latter is a human/admin-facing key also used by the
    # simulator, while TikTok sends numeric IDs such as "5655".
    tiktok_gift_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    icon: Mapped[str] = mapped_column(String, default="🎁")
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    action_type: Mapped[str] = mapped_column(String, nullable=False)  # shot|missile|heal|super_heal|special
    value: Mapped[float] = mapped_column(Float, default=0)  # negative = damage, positive = heal
    target_side: Mapped[str] = mapped_column(String, default="A")  # A|B

    # What the gift costs the viewer in TikTok coins. Tank war mode scales a
    # shot's power by this, so an expensive gift wipes out several enemies
    # while a 1-coin rose only chips one.
    coins: Mapped[int] = mapped_column(Integer, default=1)

    animation_key: Mapped[str] = mapped_column(String, default="shot")
    sound_key: Mapped[str] = mapped_column(String, default="shot")

    combo_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    multiplier: Mapped[float] = mapped_column(Float, default=1.0)

    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TikTokGiftObservation(Base):
    """A gift seen in a real TikTok LIVE but not necessarily mapped yet.

    Recording observations lets the live setup wizard show the exact numeric
    TikTok IDs sent by the current room. An operator can then map one to a
    configured game action without guessing IDs or reading container logs.
    """

    __tablename__ = "tiktok_gift_observations"

    tiktok_gift_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    coins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seen_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ComboTier(Base):
    """Configurable combo thresholds: x1 shot, x10 rajada, x25 metralhadora..."""

    __tablename__ = "combo_tiers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    animation_key: Mapped[str] = mapped_column(String, nullable=False)
    damage_multiplier: Mapped[float] = mapped_column(Float, default=1.0)


class Player(Base):
    """One spectator inside one battle session. 1 user -> 1 ball
    (configurable per battle via Battle.one_ball_per_user)."""

    __tablename__ = "players"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("battle_sessions.id"))

    user_id: Mapped[str] = mapped_column(String, nullable=False)
    username: Mapped[str] = mapped_column(String, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)

    team: Mapped[str] = mapped_column(String, nullable=False)  # A|B
    # Tank war/Eleições 2026 only: a voter must explicitly select A or B in
    # chat before their profile can enter the field or fire a gift.
    team_selected: Mapped[bool] = mapped_column(Boolean, default=False)

    damage_total: Mapped[float] = mapped_column(Float, default=0)
    heal_total: Mapped[float] = mapped_column(Float, default=0)
    gifts_total: Mapped[int] = mapped_column(Integer, default=0)
    combo_count: Mapped[int] = mapped_column(Integer, default=0)

    # Team PvP mode only: the player's own combat stats. `power` doubles as
    # health and as the value the arena scales the avatar's size by, so a
    # viewer who keeps feeding gifts visibly grows into a giant.
    power: Mapped[float] = mapped_column(Float, default=0)
    peak_power: Mapped[float] = mapped_column(Float, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    kills: Mapped[int] = mapped_column(Integer, default=0)
    eliminated: Mapped[bool] = mapped_column(Boolean, default=False)
    # Waiting for a slot: the arena holds a fixed number of fighters, so
    # whoever arrives with the field full is kept here and walks in when
    # somebody is eliminated. A queued player is not drawn and cannot be
    # bombed and cannot fire until a slot opens.
    queued: Mapped[bool] = mapped_column(Boolean, default=False)

    last_interaction: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BattleEvent(Base):
    """Full history log of every normalized event processed for a session."""

    __tablename__ = "battle_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("battle_sessions.id"))
    player_id: Mapped[str | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    gift_id: Mapped[str | None] = mapped_column(ForeignKey("gifts.id"), nullable=True)

    event_type: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    combo_count: Mapped[int] = mapped_column(Integer, default=1)
    xp_delta: Mapped[float] = mapped_column(Float, default=0)
    target_side: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MusicTrack(Base):
    """One uploaded BGM track in the playlist, tagged by the mood it plays
    for (spec section 33: normal/perigo/vitória/derrota)."""

    __tablename__ = "music_tracks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    file_url: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, default="normal")  # normal|danger|victory|defeat
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Setting(Base):
    """Small global key/value store (limits, toggles, mixer volumes, etc)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
