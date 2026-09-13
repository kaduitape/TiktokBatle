import Phaser from "phaser";
import type { CharacterPayload } from "../../types/events";

/** A character's art is either a single still image or a sprite sheet: one
 * upload holding several poses in a grid, which we play back as a loop so the
 * character moves. The admin describes the grid in columns/rows, so the frame
 * size is derived from the uploaded image instead of being typed in pixels --
 * any resolution works as long as the cells are all the same size. */

export function isAnimated(meta: CharacterPayload): boolean {
  return (meta.sprite_columns ?? 0) > 0;
}

function frameCount(meta: CharacterPayload, columns: number, rows: number): number {
  const cells = columns * rows;
  const declared = meta.sprite_frame_count ?? 0;
  return declared > 0 ? Math.min(declared, cells) : cells;
}

/** Slices an already-loaded image into frames and registers the looping
 * animation. Safe to call more than once for the same character. */
function ensureAnimation(scene: Phaser.Scene, imageKey: string, meta: CharacterPayload): string | null {
  const columns = Math.max(1, meta.sprite_columns ?? 0);
  const rows = Math.max(1, meta.sprite_rows ?? 1);
  const sheetKey = `${imageKey}__sheet`;
  const animKey = `${imageKey}__loop`;

  if (scene.anims.exists(animKey)) return animKey;

  if (!scene.textures.exists(sheetKey)) {
    const source = scene.textures.get(imageKey).getSourceImage() as HTMLImageElement;
    const frameWidth = Math.floor(source.width / columns);
    const frameHeight = Math.floor(source.height / rows);
    if (frameWidth < 1 || frameHeight < 1) return null;
    scene.textures.addSpriteSheet(sheetKey, source as any, { frameWidth, frameHeight });
  }

  const total = frameCount(meta, columns, rows);
  if (total < 2) return null;

  scene.anims.create({
    key: animKey,
    frames: scene.anims.generateFrameNumbers(sheetKey, { start: 0, end: total - 1 }),
    frameRate: Math.max(1, meta.sprite_fps ?? 10),
    repeat: -1,
  });
  return animKey;
}

/** Builds the character's game object from a loaded texture: an animated
 * Sprite when the upload is a sheet, a plain Image otherwise. Sprite extends
 * Image, so callers can keep treating the result as an Image. */
export function buildCharacterObject(
  scene: Phaser.Scene,
  imageKey: string,
  x: number,
  y: number,
  meta: CharacterPayload
): Phaser.GameObjects.Image {
  if (!isAnimated(meta)) return scene.add.image(x, y, imageKey);

  const animKey = ensureAnimation(scene, imageKey, meta);
  if (!animKey) return scene.add.image(x, y, imageKey);

  const sprite = scene.add.sprite(x, y, `${imageKey}__sheet`, 0);
  sprite.play(animKey);
  return sprite;
}
