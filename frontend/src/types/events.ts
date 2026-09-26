export interface CharacterPayload {
  id: string;
  name: string;
  image_url: string | null;
  background_url: string | null;
  team_color: string;
  scale: number;
  pos_x: number;
  pos_y: number;
  flip_h: boolean;
  shadow: boolean;
  outline: boolean;
  glow: boolean;
  /** Sprite sheet grid; 0 columns means the art is a single still image. */
  sprite_columns: number;
  sprite_rows: number;
  sprite_frame_count: number;
  sprite_fps: number;
  /** What each row of the sheet is: the base loop plus the gestures played
   * between its turns. Empty means the whole grid is one loop. */
  sprite_clips?: SpriteClipPayload[];
  /** Reaction art, swapped in briefly when the character is hit or fires. */
  hit_image_url: string | null;
  fire_image_url: string | null;
  xp_max: number;
}

/** One named row of a sprite sheet. */
export interface SpriteClipPayload {
  name: string;
  row: number;
  frames: number;
  kind?: "idle" | "gesture";
  weight?: number;
  fps?: number;
  lift?: number;
}

export interface PlayerPayload {
  id: string;
  user_id: string;
  username: string;
  nickname: string | null;
  avatar_url: string | null;
  team: "A" | "B";
  created?: boolean;
  /** This viewer already received the one-time follow boost this round. */
  followed?: boolean;
}

export interface PvpPlayerPayload extends PlayerPayload {
  power: number;
  level: number;
  kills: number;
  eliminated: boolean;
  /** Enlisted but waiting for a slot: not drawn, and cannot be bombed. */
  queued?: boolean;
}

export interface TeamTotals {
  A: { power: number; alive: number; fighters: number };
  B: { power: number; alive: number; fighters: number };
}

export type BattleMode = "character" | "team_pvp" | "tank_war";

export interface ArmyTotals {
  A: { alive: number; recruited: number; queued: number };
  B: { alive: number; recruited: number; queued: number };
}

export interface StateSyncMessage {
  type: "state_sync";
  session_id: string;
  status: string;
  winner_side: string | null;
  battle: {
    id: string;
    name: string;
    mode: BattleMode;
    background_url: string | null;
    max_players: number;
  };
  side_a: CharacterPayload;
  side_b: CharacterPayload;
  xp: { a: number; b: number };
  teams: TeamTotals;
  players: PvpPlayerPayload[];
}

export interface AttackMessage {
  type: "attack" | "heal";
  session_id: string;
  player: PlayerPayload;
  gift: {
    key: string;
    icon: string;
    action_type: "shot" | "missile" | "heal" | "super_heal" | "special";
    animation_key: string;
    sound_key: string;
  };
  quantity: number;
  combo: { count: number; tier_label: string | null; tier_animation: string | null };
  target_side: "A" | "B";
  xp_delta: number;
  xp: { a: number; b: number };
  xp_max: { a: number; b: number };
  winner_side: string | null;
  status: string;
  sudden_death: boolean;
}

export interface PlayerJoinedMessage {
  type: "player_joined";
  session_id: string;
  player: PlayerPayload;
}

export interface SuddenDeathMessage {
  type: "sudden_death";
  session_id: string;
}

export interface NewRoundCountdownMessage {
  type: "new_round_countdown";
  session_id: string;
  seconds: number;
}

export interface BattleRestartedMessage {
  type: "battle_restarted";
  session_id: string;
  xp: { a: number; b: number };
  xp_max: { a: number; b: number };
}

export interface PvpGiftMessage {
  type: "pvp_gift";
  session_id: string;
  player: PvpPlayerPayload;
  gift: {
    key: string;
    icon: string;
    action_type: "shot" | "missile" | "heal" | "super_heal" | "special";
    animation_key: string;
    sound_key: string;
  };
  quantity: number;
  combo: { count: number; tier_label: string | null; tier_animation: string | null };
  growth: { gained: number; power: number; level: number; leveled_up: boolean };
  attack: {
    target_user_id: string;
    damage: number;
    target_power: number;
    eliminated: boolean;
  } | null;
  teams: TeamTotals;
  winner_side: string | null;
  status: string;
}

export interface PvpCombatMessage {
  type: "pvp_combat";
  session_id: string;
  attacks: {
    attacker_user_id: string;
    target_user_id: string;
    damage: number;
    target_power: number;
    eliminated: boolean;
  }[];
  teams: TeamTotals;
  winner_side: string | null;
}

export interface PlayerEnlistedMessage {
  type: "player_enlisted";
  session_id: string;
  player: PvpPlayerPayload;
  switched: boolean;
  /** Live troop totals, so the counter moves as people join. */
  armies?: ArmyTotals;
  /** Arena was full: they are enlisted but waiting their turn. */
  queued?: boolean;
  queue_position?: number;
}

export interface TankShotMessage {
  type: "tank_shot";
  session_id: string;
  player: PvpPlayerPayload;
  gift: {
    key: string;
    icon: string;
    action_type: "shot" | "missile" | "heal" | "super_heal" | "special";
    animation_key: string;
    sound_key: string;
    coins: number;
    /** The only distinction between gifts in this mode besides raw damage. */
    is_special: boolean;
  };
  quantity: number;
  combo: { count: number; tier_label: string | null; tier_animation: string | null };
  shooter_side: "A" | "B";
  target_side: "A" | "B";
  damage: number;
  boss_hp: number;
  xp: { a: number; b: number };
  xp_max: { a: number; b: number };
  armies: ArmyTotals;
  winner_side: string | null;
  status: string;
}

export interface BossBombMessage {
  type: "boss_bomb";
  session_id: string;
  boss_side: "A" | "B";
  victim: {
    user_id: string;
    username: string;
    damage: number;
    power: number;
    eliminated: boolean;
  };
  armies: ArmyTotals;
  /** Whoever walked in from the queue to fill the slot this bomb opened. */
  promoted: PvpPlayerPayload | null;
}

export interface TeamHeartMessage {
  type: "team_heart";
  session_id: string;
  player: PvpPlayerPayload;
  count: number;
  target_side: "A" | "B";
  /** Life actually restored after clamping at the maximum. */
  heal: number;
  xp: { a: number; b: number };
  xp_max: { a: number; b: number };
  /** Present in team PvP, where the viewer is the healed character. */
  teams: TeamTotals | null;
}

export interface PlayerFollowedMessage {
  type: "player_followed";
  session_id: string;
  player: PvpPlayerPayload;
  previous_power: number;
  power: number;
  multiplier: number;
  teams: TeamTotals | null;
  armies: ArmyTotals | null;
}

export type ArenaMessage =
  | StateSyncMessage
  | AttackMessage
  | PlayerJoinedMessage
  | SuddenDeathMessage
  | NewRoundCountdownMessage
  | BattleRestartedMessage
  | PvpGiftMessage
  | PvpCombatMessage
  | PlayerEnlistedMessage
  | TankShotMessage
  | BossBombMessage
  | TeamHeartMessage
  | PlayerFollowedMessage;
