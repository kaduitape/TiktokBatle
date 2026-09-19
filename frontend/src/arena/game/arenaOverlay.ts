import Phaser from "phaser";
import { resolveAssetUrl } from "./avatarTexture";
import { ARENA_HEIGHT, ARENA_WIDTH } from "./constants";

/** An image the admin uploads and places over the arena.
 *
 * It replaces the legend the game used to draw from the gift list: a picture
 * the streamer designs themselves says what they want, in their own style,
 * and can be moved wherever the overlay leaves room. Nothing is drawn when no
 * image is configured.
 */
export interface OverlayConfig {
  legend_image_url?: string;
  /** Fractions of the arena, so the placement survives any scale. */
  legend_x?: number;
  legend_y?: number;
  legend_scale?: number;
}

/** Read once before the scenes build, like the rest of the arena layout. */
export const arenaOverlay: { config: OverlayConfig } = { config: {} };

export function drawArenaOverlay(scene: Phaser.Scene): void {
  const url = resolveAssetUrl(arenaOverlay.config.legend_image_url || null);
  if (!url) return;

  const x = (arenaOverlay.config.legend_x ?? 0.5) * ARENA_WIDTH;
  const y = (arenaOverlay.config.legend_y ?? 0.9) * ARENA_HEIGHT;
  const scale = arenaOverlay.config.legend_scale ?? 1;
  const key = `arena_overlay_${url.replace(/[^a-zA-Z0-9]/g, "_").slice(-48)}`;

  const place = () => {
    const img = scene.add.image(x, y, key).setOrigin(0.5).setDepth(95);
    // Scale relative to the arena width so the same image reads the same on
    // any upload size: 1.0 means half the arena wide.
    const base = (ARENA_WIDTH * 0.5) / Math.max(1, img.width);
    img.setScale(base * scale);
  };

  if (scene.textures.exists(key)) {
    place();
    return;
  }
  scene.load.setCORS("anonymous");
  scene.load.image(key, url);
  scene.load.once(`filecomplete-image-${key}`, place);
  scene.load.start();
}
