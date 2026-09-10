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
  xp_max: number;
}

export interface PlayerPayload {
  id: string;
  user_id: string;
  username: string;
  nickname: string | null;
  avatar_url: string | null;
  team: "A" | "B";
  created?: boolean;
}

export interface StateSyncMessage {
  type: "state_sync";
  session_id: string;
  status: string;
  winner_side: string | null;
  battle: { id: string; name: string; background_url: string | null; max_players: number };
  side_a: CharacterPayload;
  side_b: CharacterPayload;
  xp: { a: number; b: number };
  players: PlayerPayload[];
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

export type ArenaMessage =
  | StateSyncMessage
  | AttackMessage
  | PlayerJoinedMessage
  | SuddenDeathMessage
  | NewRoundCountdownMessage
  | BattleRestartedMessage;
