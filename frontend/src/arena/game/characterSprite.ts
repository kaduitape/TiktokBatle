import Phaser from "phaser";
import type { CharacterPayload, SpriteMovementPayload } from "../../types/events";
import { CharacterAnimator, readClips, type SpriteClip } from "./characterAnimator";

/** A character's art is either a single still image or a sprite sheet: one
 * upload holding several poses in a grid, which we play back as a loop so the
 * character moves. The admin describes the grid in columns/rows, so the frame
 * size is derived from the uploaded image instead of being typed in pixels --
 * any resolution works as long as the cells are all the same size. */

export function isAnimated(meta: CharacterPayload): boolean {
  return (meta.sprite_columns ?? 0) > 0;
}

/** Texture keys fold in the image's own URL, not just the character id.
 * Keying by id alone meant Phaser kept serving the art it cached the first
 * time: changing a character's drawing in the panel changed nothing on an
 * arena that was already open, which is exactly what an OBS source is. */
export function textureKeyFor(meta: CharacterPayload, url: string | null | undefined, suffix = ""): string {
  const stamp = (url || "none").replace(/[^a-zA-Z0-9]/g, "_").slice(-48);
  return `char_${meta.id}_${stamp}${suffix}`;
}

/** Where a character's own movement sounds are played. Each scene points it
 * at its AudioManager on creation, so the mixer's volume applies and the
 * animator does not need to know which scene it lives in. */
let soundSink: ((url: string) => void) | null = null;

export function setCharacterSoundSink(sink: ((url: string) => void) | null): void {
  soundSink = sink;
}

function playCharacterSound(meta: CharacterPayload, movement: string): void {
  const url = meta.sprite_sounds?.[movement];
  if (url && soundSink) soundSink(url);
}

/** Reaction art: stills swapped in for a moment when the character does
 * something. `hit` plays when it takes damage, `fire` when it shoots. */
export type ActionKind = "hit" | "fire";

const actionUrl = (meta: CharacterPayload, kind: ActionKind): string | null =>
  (kind === "hit" ? meta.hit_image_url : meta.fire_image_url) ?? null;

export const actionTextureKey = (meta: CharacterPayload, kind: ActionKind): string =>
  textureKeyFor(meta, actionUrl(meta, kind), `__${kind}`);

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
  // An animated character has an animator that owns playback; putting it back
  // at rest means handing the sprite back to it, not replaying one key. A
  // still, or a sheet the animator refused, falls back to the plain texture.
  const animated = !!animatorFor(sprite);
  const legacyLoop = !animated && isAnimated(meta) && scene_hasAnim(sprite, `${imageKey}__loop`);
  sprite.setData(IDLE_POSE, {
    textureKey: animated || legacyLoop ? `${imageKey}__sheet` : imageKey,
    animKey: legacyLoop ? `${imageKey}__loop` : null,
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
  // The sound belongs to the movement, not to the art: a character with a
  // hit sound but no hit drawing still says "ouch".
  if (sprite.active) playCharacterSound(meta, kind);

  const idle = sprite.getData(IDLE_POSE) as IdlePose | undefined;
  const reactionAnim = (sprite.getData(REACTION_ANIMS) as Record<string, string> | undefined)?.[kind];
  if (idle && sprite.active && reactionAnim && scene.anims.exists(reactionAnim)) {
    // A movement of its own: play it through once, then hand the sprite back.
    const token = idle.token + 1;
    idle.token = token;
    const animator = animatorFor(sprite);
    animator?.suspend();
    const asSprite = sprite as Phaser.GameObjects.Sprite;
    asSprite.anims.timeScale = 1;
    asSprite.play({ key: reactionAnim, repeat: 0 }, true);
    refitToIdle(sprite);
    asSprite.once(Phaser.Animations.Events.ANIMATION_COMPLETE, () => {
      if (!sprite.active || idle.token !== token) return;
      animator?.resume();
      refitToIdle(sprite);
    });
    return true;
  }

  const key = actionTextureKey(meta, kind);
  if (!idle || !scene.textures.exists(key) || !sprite.active) return false;

  const token = idle.token + 1;
  idle.token = token;

  // The idle loop and the reaction still cannot both drive the sprite: the
  // animator is told to let go, and told again when the reaction is over.
  const animator = animatorFor(sprite);
  animator?.suspend();

  const asSprite = sprite as Phaser.GameObjects.Sprite;
  asSprite.anims?.stop?.();
  sprite.setTexture(key);
  fitHeight(sprite, idle.targetHeight);

  scene.time.delayedCall(ms, () => {
    // A newer reaction started while this one was showing -- it owns the
    // sprite now, and will restore the idle pose when it finishes.
    if (!sprite.active || idle.token !== token) return;
    if (animator) {
      // resume() replays the base clip, which sets the sheet and the frame
      // itself; the refit comes after because the frame size changed.
      animator.resume();
      fitHeight(sprite, idle.targetHeight);
      return;
    }
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

/** Every clip the sheet holds, and whether the character actually declared
 * them. Without a declared list the whole grid is one looping clip, spanning
 * every row -- which is how every character behaved before clips existed, and
 * what a sheet built by scripts/make_spritesheet.py still is. */
function clipsFor(
  meta: CharacterPayload,
  columns: number,
  rows: number
): { clips: SpriteClip[]; declared: boolean } {
  const declared = readClips(meta).filter((clip) => clip.row < rows);
  if (declared.length) return { clips: declared, declared: true };

  const total = frameCount(meta, columns, rows);
  return {
    clips: [{ name: "idle", row: 0, frames: total, kind: "idle", weight: 1 }],
    declared: false,
  };
}

/** Registers one Phaser animation per clip, slicing the row it names.
 * Safe to call more than once for the same character. */
function ensureClipAnimations(
  scene: Phaser.Scene,
  imageKey: string,
  meta: CharacterPayload,
): { clips: SpriteClip[]; sheetKey: string; columns: number } | null {
  const columns = Math.max(1, meta.sprite_columns ?? 0);
  const rows = Math.max(1, meta.sprite_rows ?? 1);
  const sheetKey = `${imageKey}__sheet`;

  if (!scene.textures.exists(sheetKey)) {
    const source = scene.textures.get(imageKey).getSourceImage() as HTMLImageElement;
    const frameWidth = Math.floor(source.width / columns);
    const frameHeight = Math.floor(source.height / rows);
    if (frameWidth < 1 || frameHeight < 1) return null;
    scene.textures.addSpriteSheet(sheetKey, source as any, { frameWidth, frameHeight });
  }

  const { clips, declared } = clipsFor(meta, columns, rows);
  const baseFps = Math.max(1, meta.sprite_fps ?? 10);

  for (const clip of clips) {
    const key = `${imageKey}__${clip.name}_${clip.row}`;
    if (scene.anims.exists(key)) continue;
    // A declared clip owns one row: its frames start where that row starts and
    // stop at its end. The undeclared fallback is the whole grid as one loop,
    // so it has to be allowed to run past the end of the first row -- capping
    // it at `columns` would silently drop every row but the first from sheets
    // that were animating fine before clips existed.
    const start = clip.row * columns;
    const end = declared
      ? start + Math.min(clip.frames, columns) - 1
      : start + Math.min(clip.frames, columns * rows) - 1;
    if (end < start) continue;
    scene.anims.create({
      key,
      frames: scene.anims.generateFrameNumbers(sheetKey, { start, end }),
      frameRate: clip.fps ?? baseFps,
      repeat: clip.kind === "gesture" ? 0 : -1,
    });
  }

  return { clips, sheetKey, columns };
}

/** Kept for the single-loop path the idle-pose bookkeeping still refers to. */
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

// ---------------------------------------------------------------------------
// One sheet per movement
// ---------------------------------------------------------------------------

export function movementsOf(meta: CharacterPayload): SpriteMovementPayload[] {
  return (meta.sprite_movements ?? []).filter(
    (m) => m && m.image_url && (m.frames ?? 0) > 0 && (m.columns ?? 0) > 0,
  );
}

export function hasMovements(meta: CharacterPayload): boolean {
  return movementsOf(meta).some((m) => m.kind === "idle");
}

const movementSheetKey = (meta: CharacterPayload, m: SpriteMovementPayload) =>
  textureKeyFor(meta, m.image_url, `__mv_${m.name}__sheet`);

const movementAnimKey = (meta: CharacterPayload, m: SpriteMovementPayload) =>
  `${movementSheetKey(meta, m)}__play`;

/** Loads every movement's sheet the character needs, sliced by its grid.
 * Resolves once all of them are in (a sheet that fails to load is skipped,
 * not waited on forever). */
export function loadMovementTextures(
  scene: Phaser.Scene,
  meta: CharacterPayload,
  resolve: (url: string | null) => string | null,
): Promise<void> {
  const pending = movementsOf(meta).filter((m) => !scene.textures.exists(movementSheetKey(meta, m)));
  if (!pending.length) return Promise.resolve();

  return new Promise((done) => {
    let left = pending.length;
    const finish = () => {
      left -= 1;
      if (left <= 0) {
        scene.load.off("loaderror", onError);
        done();
      }
    };
    const raw = new Map<string, SpriteMovementPayload>();
    const onError = (file: Phaser.Loader.File) => {
      if (raw.has(file.key)) finish();
    };
    scene.load.on("loaderror", onError);
    scene.load.setCORS("anonymous");

    for (const m of pending) {
      const url = resolve(m.image_url);
      const sheetKey = movementSheetKey(meta, m);
      const rawKey = `${sheetKey}__raw`;
      if (!url) {
        finish();
        continue;
      }
      raw.set(rawKey, m);
      scene.load.image(rawKey, url);
      scene.load.once(`filecomplete-image-${rawKey}`, () => {
        // Sliced by the grid the server reported, so the frame size always
        // matches the file -- no pixel sizes to get out of step.
        if (!scene.textures.exists(sheetKey)) {
          const source = scene.textures.get(rawKey).getSourceImage() as HTMLImageElement;
          scene.textures.addSpriteSheet(sheetKey, source as any, {
            frameWidth: Math.floor(source.width / Math.max(1, m.columns)),
            frameHeight: Math.floor(source.height / Math.max(1, m.rows)),
          });
        }
        finish();
      });
    }
    scene.load.start();
  });
}

/** One Phaser animation per movement, from that movement's own sheet. */
function ensureMovementAnimations(scene: Phaser.Scene, meta: CharacterPayload): SpriteClip[] {
  const baseFps = Math.max(1, meta.sprite_fps ?? 10);
  const clips: SpriteClip[] = [];
  for (const m of movementsOf(meta)) {
    const sheetKey = movementSheetKey(meta, m);
    if (!scene.textures.exists(sheetKey)) continue;
    const key = movementAnimKey(meta, m);
    if (!scene.anims.exists(key)) {
      scene.anims.create({
        key,
        frames: scene.anims.generateFrameNumbers(sheetKey, { start: 0, end: Math.max(0, m.frames - 1) }),
        frameRate: m.fps && m.fps > 0 ? m.fps : baseFps,
        repeat: m.kind === "idle" ? -1 : 0,
      });
    }
    if (m.kind === "idle" || m.kind === "gesture") {
      clips.push({
        name: m.kind === "idle" ? "base" : m.name,
        row: 0,
        frames: m.frames,
        fps: m.fps && m.fps > 0 ? m.fps : undefined,
        kind: m.kind === "idle" ? "idle" : "gesture",
        weight: m.weight && m.weight > 0 ? m.weight : 1,
        lift: m.lift && m.lift > 0 ? m.lift : undefined,
        animKey: key,
      });
    }
  }
  return clips;
}

/** Puts the sprite back at its resting on-screen height. Separate movement
 * sheets can have different cell sizes, so this runs on every switch. */
function refitToIdle(sprite: Phaser.GameObjects.Image): void {
  const idle = sprite.getData(IDLE_POSE) as IdlePose | undefined;
  if (idle && sprite.active) fitHeight(sprite, idle.targetHeight);
}

const REACTION_ANIMS = "reactionAnims";

function buildFromMovements(
  scene: Phaser.Scene,
  imageKey: string,
  x: number,
  y: number,
  meta: CharacterPayload,
  options: { gesturesOnly?: boolean },
): Phaser.GameObjects.Sprite | null {
  const clips = ensureMovementAnimations(scene, meta);
  const idleMovement = movementsOf(meta).find((m) => m.kind === "idle");
  if (!clips.length || !idleMovement) return null;

  const idleSheet = movementSheetKey(meta, idleMovement);
  const sprite = scene.add.sprite(x, y, idleSheet, 0);

  // Hit and fire are animations of their own now, not stills.
  const reactions: Record<string, string> = {};
  for (const m of movementsOf(meta)) {
    if ((m.kind === "hit" || m.kind === "fire") && scene.anims.exists(movementAnimKey(meta, m))) {
      reactions[m.kind] = movementAnimKey(meta, m);
    }
  }
  sprite.setData(REACTION_ANIMS, reactions);

  const animator = new CharacterAnimator(scene, sprite, imageKey, clips, Math.max(1, meta.sprite_fps ?? 10), {
    gesturesOnly: options.gesturesOnly,
    sounds: meta.sprite_sounds ?? {},
    playSound: (url) => soundSink?.(url),
    idleTexture: idleSheet,
    idleFrame: 0,
    refit: () => refitToIdle(sprite),
  });
  animators.set(sprite, animator);
  sprite.once(Phaser.GameObjects.Events.DESTROY, () => animator.destroy());
  animator.start();
  return sprite;
}

/** Builds the character's game object from a loaded texture: an animated
 * Sprite when the upload is a sheet, a plain Image otherwise. Sprite extends
 * Image, so callers can keep treating the result as an Image. */
/** Animators live as long as their sprite, so a scene teardown can stop them
 * instead of leaving timers firing at a destroyed object. */
const animators = new WeakMap<Phaser.GameObjects.GameObject, CharacterAnimator>();

export function animatorFor(
  object: Phaser.GameObjects.GameObject | null | undefined,
): CharacterAnimator | undefined {
  return object ? animators.get(object) : undefined;
}

export function buildCharacterObject(
  scene: Phaser.Scene,
  imageKey: string,
  x: number,
  y: number,
  meta: CharacterPayload,
  options: { gesturesOnly?: boolean } = {},
): Phaser.GameObjects.Image {
  if (hasMovements(meta)) {
    const sprite = buildFromMovements(scene, imageKey, x, y, meta, options);
    if (sprite) return sprite;
  }

  if (!isAnimated(meta)) return scene.add.image(x, y, imageKey);

  const built = ensureClipAnimations(scene, imageKey, meta);
  if (!built || !built.clips.length) return scene.add.image(x, y, imageKey);

  const sprite = scene.add.sprite(x, y, built.sheetKey, 0);

  // The animator owns playback from here: it loops the base clip, drifts the
  // tempo so the beat never locks in, and slips a gesture in now and then.
  const animator = new CharacterAnimator(
    scene,
    sprite,
    imageKey,
    built.clips,
    Math.max(1, meta.sprite_fps ?? 10),
    {
      gesturesOnly: options.gesturesOnly,
      sounds: meta.sprite_sounds ?? {},
      playSound: (url) => soundSink?.(url),
      idleFrame:
        (built.clips.find((clip) => clip.kind === "idle")?.row ?? built.clips[0].row) *
        built.columns,
    },
  );
  animators.set(sprite, animator);
  sprite.once(Phaser.GameObjects.Events.DESTROY, () => animator.destroy());
  animator.start();
  return sprite;
}

/** Draws (or replaces) the arena backdrop. Keyed by URL and holding on to the
 * image it made, so a republished state swaps the backdrop instead of stacking
 * a second one behind the first. */
export function setBackground(
  scene: Phaser.Scene,
  url: string | null | undefined,
  width: number,
  height: number,
  current: Phaser.GameObjects.Image | null
): Phaser.GameObjects.Image | null {
  if (!url) {
    current?.destroy();
    return null;
  }
  const key = `bg_${url.replace(/[^a-zA-Z0-9]/g, "_").slice(-48)}`;
  if (current?.texture?.key === key) return current;
  current?.destroy();

  const place = () =>
    scene.add.image(width / 2, height / 2, key).setDisplaySize(width, height).setDepth(-9);

  if (scene.textures.exists(key)) return place();

  // Not loaded yet: the caller keeps null until the file arrives, and the
  // image inserts itself then.
  scene.load.setCORS("anonymous");
  scene.load.image(key, url);
  scene.load.once(`filecomplete-image-${key}`, () => place());
  scene.load.start();
  return null;
}
