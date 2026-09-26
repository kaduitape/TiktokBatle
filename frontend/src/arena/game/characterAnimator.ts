import Phaser from "phaser";
import type { CharacterPayload } from "../../types/events";

/** Making a character look alive instead of wound up.
 *
 * A single row looping at a fixed frame rate is a machine: the same frames,
 * the same speed, restarting at the same instant forever. The eye picks that
 * up in seconds.
 *
 * Three things break the pattern here, and they compound:
 *
 * 1. **Gestures.** Rows past the first are one-off clips -- a blink, a hop, a
 *    tongue out -- slipped between loops of the base row at uneven intervals.
 *    The character does something small when nothing is happening, which is
 *    what a living one does.
 * 2. **Tempo.** Each loop runs a few percent faster or slower than the last,
 *    so the beat never locks in.
 * 3. **Breathing.** A slow, continuous rise and fall applied to the sprite
 *    itself, independent of the frames, so the character is never perfectly
 *    still even on a single-frame pose.
 */

export interface SpriteClip {
  name: string;
  row: number;
  frames: number;
  fps?: number;
  /** "idle" loops; "gesture" plays once and hands back to idle. */
  kind?: "idle" | "gesture";
  /** Relative chance of being picked. Higher shows up more often. */
  weight?: number;
  /** Fraction of the character's height it rises while the clip plays.
   * The sheet bottom-aligns every frame on its feet, so a hop drawn as art
   * never leaves the floor -- this is what actually lifts it. */
  lift?: number;
}

/** How long between gestures. A real character does not twitch every second,
 * and it does not stand still for a minute either. */
const GESTURE_GAP_MS = { min: 3200, max: 9000 };

/** How far the loop's speed drifts each time round. Enough to unlock the
 * beat, not enough to look like a frame-rate problem. */
const TEMPO_DRIFT = 0.12;

const BREATH = { periodMs: 2600, amount: 0.022 };

/** How long a hop takes, up and back down. */
const LIFT_MS = 420;

export function readClips(meta: CharacterPayload): SpriteClip[] {
  const raw = (meta as { sprite_clips?: unknown }).sprite_clips;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((c): c is SpriteClip => !!c && typeof c === "object" && typeof (c as SpriteClip).row === "number")
    .map((c) => ({
      name: String(c.name ?? `clip_${c.row}`),
      row: Math.max(0, Math.floor(c.row)),
      frames: Math.max(1, Math.floor(c.frames ?? 1)),
      fps: c.fps && c.fps > 0 ? c.fps : undefined,
      kind: c.kind === "gesture" ? "gesture" : "idle",
      weight: c.weight && c.weight > 0 ? c.weight : 1,
      lift: c.lift && c.lift > 0 ? Math.min(1, c.lift) : undefined,
    }));
}

export interface CharacterAnimatorOptions {
  /** Tank War leaves the character stopped between randomly chosen gestures. */
  gesturesOnly?: boolean;
  /** Absolute sheet frame used while a gestures-only character is waiting. */
  idleFrame?: number;
}

/** Drives one character's sprite. Created per character, destroyed with it. */
export class CharacterAnimator {
  private scene: Phaser.Scene;
  private sprite: Phaser.GameObjects.Sprite;
  private idle: SpriteClip;
  private gestures: SpriteClip[];
  private baseFps: number;
  private keyPrefix: string;
  private timer: Phaser.Time.TimerEvent | null = null;
  private breathTween: Phaser.Tweens.Tween | null = null;
  private liftTween: Phaser.Tweens.Tween | null = null;
  /** Where the sprite sits when it is not mid-hop. */
  private groundY = 0;
  private stopped = false;
  /** A reaction (taking a hit, attacking) owns the sprite while it plays. */
  private suspended = false;
  private gesturesOnly = false;
  private idleFrame = 0;

  constructor(
    scene: Phaser.Scene,
    sprite: Phaser.GameObjects.Sprite,
    keyPrefix: string,
    clips: SpriteClip[],
    baseFps: number,
    options: CharacterAnimatorOptions = {},
  ) {
    this.scene = scene;
    this.sprite = sprite;
    this.keyPrefix = keyPrefix;
    this.baseFps = Math.max(1, baseFps);
    this.idle = clips.find((c) => c.kind === "idle") ?? clips[0];
    this.gestures = clips.filter((c) => c.kind === "gesture");
    this.gesturesOnly = options.gesturesOnly ?? false;
    this.idleFrame = Math.max(0, options.idleFrame ?? 0);
  }

  start(): void {
    if (this.stopped) return;
    if (this.gesturesOnly) this.showStillFrame();
    else {
      this.playIdle();
      this.startBreathing();
    }
    this.scheduleGesture();
  }

  /** Hand the sprite over for a reaction still, and take it back after. */
  suspend(): void {
    this.suspended = true;
    this.timer?.remove();
    this.timer = null;
    this.sprite.off(Phaser.Animations.Events.ANIMATION_COMPLETE);
    this.dropToGround();
  }

  resume(): void {
    if (this.stopped) return;
    this.suspended = false;
    if (this.gesturesOnly) this.showStillFrame();
    else this.playIdle();
    this.scheduleGesture();
  }

  destroy(): void {
    this.stopped = true;
    this.timer?.remove();
    this.timer = null;
    this.breathTween?.remove();
    this.breathTween = null;
    this.dropToGround();
  }

  private animKey(clip: SpriteClip): string {
    return `${this.keyPrefix}__${clip.name}_${clip.row}`;
  }

  private playIdle(): void {
    if (!this.sprite.active || !this.idle) return;
    const key = this.animKey(this.idle);
    if (!this.scene.anims.exists(key)) return;
    this.sprite.play({ key, repeat: -1 }, true);
    this.driftTempo();
  }

  /** Tank War deliberately has no perpetual animation. The first frame of
   * the idle row is a neutral waiting pose until a random gesture is picked. */
  private showStillFrame(): void {
    if (!this.sprite.active || !this.idle) return;
    this.sprite.anims.stop();
    this.sprite.setTexture(`${this.keyPrefix}__sheet`, this.idleFrame);
    this.sprite.anims.timeScale = 1;
  }

  /** Nudge the playback rate so consecutive loops never match. */
  private driftTempo(): void {
    const drift = Phaser.Math.FloatBetween(1 - TEMPO_DRIFT, 1 + TEMPO_DRIFT);
    this.sprite.anims.timeScale = drift;
  }

  /** A slow rise and fall, so the character is never perfectly still.
   *
   * It drives a counter rather than scaleY directly, and reads scaleX as the
   * resting size every frame. Tweening scaleY from a value captured once meant
   * the first refit -- which the scene does right after the sprite is built,
   * and again after every reaction still -- was immediately undone by a tween
   * still animating towards the size the character had before it.
   */
  private startBreathing(): void {
    if (!this.sprite.active) return;
    const phase = { value: 0 };
    this.breathTween = this.scene.tweens.add({
      targets: phase,
      value: 1,
      duration: BREATH.periodMs / 2,
      yoyo: true,
      repeat: -1,
      ease: "Sine.easeInOut",
      // Start somewhere random in the cycle, so a crowd does not breathe in
      // unison like a chorus line.
      delay: Phaser.Math.Between(0, BREATH.periodMs),
      onUpdate: () => {
        if (!this.sprite.active) return;
        this.sprite.scaleY = this.sprite.scaleX * (1 + BREATH.amount * phase.value);
      },
    });
  }

  /** Lifts the sprite off the floor for the length of a clip and puts it
   * back. Cancelled by a reaction, which returns it to the ground first. */
  private hop(clip: SpriteClip, durationMs: number): void {
    if (!clip.lift || !this.sprite.active) return;
    this.dropToGround();
    this.groundY = this.sprite.y;
    const rise = this.sprite.displayHeight * clip.lift;
    this.liftTween = this.scene.tweens.add({
      targets: this.sprite,
      y: this.groundY - rise,
      duration: Math.max(120, Math.min(LIFT_MS, durationMs) / 2),
      yoyo: true,
      ease: "Quad.easeOut",
      onComplete: () => {
        this.liftTween = null;
        if (this.sprite.active) this.sprite.y = this.groundY;
      },
    });
  }

  private dropToGround(): void {
    if (!this.liftTween) return;
    this.liftTween.remove();
    this.liftTween = null;
    if (this.sprite.active) this.sprite.y = this.groundY;
  }

  private scheduleGesture(): void {
    if (this.stopped || this.suspended || !this.gestures.length) return;
    this.timer?.remove();
    this.timer = this.scene.time.delayedCall(
      Phaser.Math.Between(GESTURE_GAP_MS.min, GESTURE_GAP_MS.max),
      () => this.playGesture(),
    );
  }

  private pickGesture(): SpriteClip | null {
    const total = this.gestures.reduce((sum, c) => sum + (c.weight ?? 1), 0);
    if (total <= 0) return null;
    let roll = Phaser.Math.FloatBetween(0, total);
    for (const clip of this.gestures) {
      roll -= clip.weight ?? 1;
      if (roll <= 0) return clip;
    }
    return this.gestures[this.gestures.length - 1];
  }

  private playGesture(): void {
    if (this.stopped || this.suspended || !this.sprite.active) return;
    const clip = this.pickGesture();
    const key = clip ? this.animKey(clip) : null;
    if (!clip || !key || !this.scene.anims.exists(key)) {
      this.scheduleGesture();
      return;
    }

    this.sprite.anims.timeScale = 1;
    // A handler left over from a gesture a reaction interrupted would fire on
    // this one and schedule a second timer.
    this.sprite.off(Phaser.Animations.Events.ANIMATION_COMPLETE);
    this.sprite.play({ key, repeat: 0 }, true);
    this.hop(clip, (clip.frames / (clip.fps ?? this.baseFps)) * 1000);
    this.sprite.once(Phaser.Animations.Events.ANIMATION_COMPLETE, () => {
      // A reaction may have taken the sprite while the gesture ran.
      if (this.stopped || this.suspended || !this.sprite.active) return;
      if (this.gesturesOnly) this.showStillFrame();
      else this.playIdle();
      this.scheduleGesture();
    });
  }
}
