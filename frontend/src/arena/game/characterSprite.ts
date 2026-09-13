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

/** Reaction art: stills swapped in for a moment when the character does
 * something. `hit` plays when it takes damage, `fire` when it shoots. */
export type ActionKind = "hit" | "fire";

const actionUrl = (meta: CharacterPayload, kind: ActionKind): string | null =>
  (kind === "hit" ? meta.hit_image_url : meta.fire_image_url) ?? null;

export const actionTextureKey = (meta: CharacterPayload, kind: ActionKind): string =>
  `char_${meta.id}__${kind}`;

/** Loads whichever reaction stills the character has. Fire-and-forget: if one
 * has not arrived by the time it is needed, the swap is simply skipped. */
export function preloadActionArt(
  scene: Phaser.Scene,
  meta: CharacterPayload,
  resolve: (url: string | null) => string | null
): void {
  (["hit", "fire"] as const).forEach((kind) => {
    const url = resolve(actionUrl(meta, kind));
    const key = actionTextureKey(meta, kind);
    if (!url || scene.textures.exists(key)) return;
    scene.load.setCORS("anonymous");
    scene.load.image(key, url);
    scene.load.start();
  });
}

interface IdlePose {
  textureKey: string;
  animKey: string | null;
  targetHeight: number;
  /** Bumped on every swap so a late restore from an earlier swap is ignored. */
  token: number;
}

const IDLE_POSE = "idlePose";

/** Scales the sprite so it keeps the same on-screen height no matter which
 * texture it is showing -- reaction art rarely has the idle art's dimensions. */
function fitHeight(sprite: Phaser.GameObjects.Image, targetHeight: number): void {
  const height = sprite.height || 1;
  sprite.setScale(targetHeight / height);
}

/** Records what the sprite looks like at rest, so a reaction can be undone. */
export function rememberIdlePose(
  sprite: Phaser.GameObjects.Image,
  meta: CharacterPayload,
  imageKey: string,
  targetHeight: number
): void {
  const animated = isAnimated(meta) && scene_hasAnim(sprite, `${imageKey}__loop`);
  sprite.setData(IDLE_POSE, {
    textureKey: animated ? `${imageKey}__sheet` : imageKey,
    animKey: animated ? `${imageKey}__loop` : null,
    targetHeight,
    token: 0,
  } satisfies IdlePose);
  fitHeight(sprite, targetHeight);
}

function scene_hasAnim(sprite: Phaser.GameObjects.Image, key: string): boolean {
  return !!sprite.scene?.anims?.exists(key);
}

/** Swaps in the reaction art for `ms`, then puts the idle art back. Returns
 * false when the character has no art for that action, so the caller can fall
 * back to the tint-and-shake it already had. */
export function flashAction(
  scene: Phaser.Scene,
  sprite: Phaser.GameObjects.Image,
  meta: CharacterPayload,
  kind: ActionKind,
  ms = 320
): boolean {
  const key = actionTextureKey(meta, kind);
  const idle = sprite.getData(IDLE_POSE) as IdlePose | undefined;
  if (!idle || !scene.textures.exists(key) || !sprite.active) return false;

  const token = idle.token + 1;
  idle.token = token;

  const asSprite = sprite as Phaser.GameObjects.Sprite;
  asSprite.anims?.stop?.();
  sprite.setTexture(key);
  fitHeight(sprite, idle.targetHeight);

  scene.time.delayedCall(ms, () => {
    // A newer reaction started while this one was showing -- it owns the
    // sprite now, and will restore the idle pose when it finishes.
    if (!sprite.active || idle.token !== token) return;
    sprite.setTexture(idle.textureKey);
    fitHeight(sprite, idle.targetHeight);
    if (idle.animKey) asSprite.play?.(idle.animKey);
  });
  return true;
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
