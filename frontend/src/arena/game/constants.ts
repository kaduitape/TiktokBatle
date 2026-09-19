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
