export const ARENA_WIDTH = 1080;
export const ARENA_HEIGHT = 1920;

export const AVATAR_DIAMETER = 78;
export const AVATAR_DIAMETER_GIANT = 160;

export const CEILING_Y = 40;

/** How much of the bottom the streaming overlay covers.
 *
 * On TikTok the chat sits over the lower part of the screen, and everything
 * this arena anchors to the bottom -- the ground the avatars stand on, the
 * feed, the powers legend -- was landing under it. Reserving a strip here
 * lifts all of them together, so they keep their relationship to each other
 * and simply stop where the chat begins.
 *
 * Set once from the admin setting before a scene builds; read through the
 * getters below so every measurement follows it.
 */
export const arenaLayout = {
  bottomSafePx: 0,
  get floorY(): number {
    return ARENA_HEIGHT - 260 - this.bottomSafePx;
  },
  get feedY(): number {
    // Kept 50px below the ground, as it has always been drawn.
    return this.floorY + 50;
  },
};

/** The ground with no overlay reserved -- the default layout. */
export const FLOOR_Y = ARENA_HEIGHT - 260;

export const SPAWN_TOP_Y = -60;

export const CENTER_X = ARENA_WIDTH / 2;

export const SIDE_A_ZONE = { xMin: 20, xMax: CENTER_X - 20 };
export const SIDE_B_ZONE = { xMin: CENTER_X + 20, xMax: ARENA_WIDTH - 20 };

export const XP_BAR_Y = 150;
export const FEED_Y = ARENA_HEIGHT - 210;
export const RANKING_Y = 360;

/** Where a character stands horizontally, given the side it was cast as.
 *
 * pos_x is stored on the Character, but which half of the arena it belongs to
 * is decided by the battle -- the same character can be Lado A in one battle
 * and Lado B in another. So a character whose stored x sits in the enemy's
 * half is mirrored into its own.
 *
 * This exists because two characters created one after the other both keep
 * whatever the form defaulted to, and used to land exactly on top of each
 * other on the left. Guarding against one particular default value did not
 * help: the panel's default (0.25) and a saved model's (0.5) are different
 * numbers, and neither is a statement that the character belongs on the left.
 * Mirroring works whatever the number is.
 */
export function sideAwarePosX(posX: number | null | undefined, side: "A" | "B"): number {
  const x = typeof posX === "number" && Number.isFinite(posX) ? posX : 0.5;

  // Dead centre belongs to nobody, so each side takes its natural spot.
  if (Math.abs(x - 0.5) < 0.02) return side === "A" ? 0.25 : 0.75;

  const onEnemyHalf = side === "A" ? x > 0.5 : x < 0.5;
  return onEnemyHalf ? 1 - x : x;
}
