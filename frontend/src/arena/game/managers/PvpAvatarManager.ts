import Phaser from "phaser";
import type { PvpPlayerPayload } from "../../../types/events";
import { bakeAvatarTexture } from "../avatarTexture";
import { arenaLayout, CEILING_Y, CENTER_X, SIDE_A_ZONE, SIDE_B_ZONE, SPAWN_TOP_Y } from "../constants";

// Baked at more than twice the smallest on-screen size so the circle stays
// crisp, and never below it, which is what made small avatars look ragged.
const TEXTURE_SIZE = 160;
const MIN_DIAMETER = 64;
const MAX_DIAMETER = 190;
const POWER_FOR_MIN = 100;
/** A visible breathing room so profile circles do not begin on top of one
 * another before Matter has a chance to resolve their collisions. */
const SPAWN_GAP = 8;
const SPAWN_POSITION_ATTEMPTS = 48;
const ENTRY_DIAMETER = 150;
const ENTRY_DURATION_MS = 720;

export interface Fighter {
  sprite: Phaser.Physics.Matter.Sprite;
  hpBarBg: Phaser.GameObjects.Rectangle;
  hpBar: Phaser.GameObjects.Rectangle;
  powerLabel: Phaser.GameObjects.Text;
  player: PvpPlayerPayload;
  power: number;
  peakPower: number;
  diameter: number;
  entering: boolean;
  pendingAttackGrowth: number;
  wanderEvent?: Phaser.Time.TimerEvent;
}

export interface PvpAvatarOptions {
  /** Lower = falls faster. The default drifts down like a balloon, which reads
   * well when a handful of fighters trickle in; a packed arena needs them on
   * the floor quickly so they stop covering the scoreboard. */
  frictionAir?: number;
  /** Where a dropping-in fighter appears. Defaults to just above the screen;
   * a scene with a tall HUD sets it lower so arrivals never cross the bars. */
  spawnY?: number;
  /** Vertical centre bounds for fighters restored from the live state. A
   * scene can keep its whole army in a dedicated lower field. */
  fieldYMin?: number;
  fieldYMax?: number;
  /** Off keeps every avatar the same size: tank war fields uniform soldiers
   * whose bar drains, while PvP grows its fighters with their power. */
  scaleWithPower?: boolean;
  showPowerLabel?: boolean;
  /** Tank war presents a new voter in the centre before it takes its place
   * among its side's troops. Other modes retain their existing drop-in. */
  centerEntrance?: boolean;
  /** Small, infrequent impulses keep an army looking alive after it settles. */
  idleWander?: boolean;
}

/** Manages the circular avatars that fight in the arena: an HP bar that
 * drains above each one, and (in PvP) a diameter that grows with the
 * owner's power, the way the reference battles do. */
export class PvpAvatarManager {
  private scene: Phaser.Scene;
  private fighters = new Map<string, Fighter>();
  private options: Required<PvpAvatarOptions>;

  constructor(scene: Phaser.Scene, options: PvpAvatarOptions = {}) {
    this.scene = scene;
    this.options = {
      scaleWithPower: options.scaleWithPower ?? true,
      showPowerLabel: options.showPowerLabel ?? true,
      centerEntrance: options.centerEntrance ?? false,
      idleWander: options.idleWander ?? false,
      frictionAir: options.frictionAir ?? 0.015,
      spawnY: options.spawnY ?? SPAWN_TOP_Y,
      fieldYMin: options.fieldYMin ?? CEILING_Y,
      fieldYMax: options.fieldYMax ?? arenaLayout.floorY - 200,
    };
  }

  get(userId: string): Fighter | undefined {
    return this.fighters.get(userId);
  }

  all(): Fighter[] {
    return Array.from(this.fighters.values());
  }

  aliveOf(team: "A" | "B"): Fighter[] {
    return this.all().filter((f) => f.player.team === team && f.power > 0);
  }

  /** Logarithmic so a 30x power lead reads as "much bigger" without a single
   * whale covering the whole arena. */
  private diameterFor(power: number): number {
    if (!this.options.scaleWithPower) return MIN_DIAMETER;
    const ratio = Math.max(1, power / POWER_FOR_MIN);
    const diameter = MIN_DIAMETER + Math.log2(ratio) * 26;
    return Phaser.Math.Clamp(diameter, MIN_DIAMETER, MAX_DIAMETER);
  }

  async spawnOrGet(player: PvpPlayerPayload, teamColor: string, dropIn = true): Promise<Fighter> {
    const existing = this.fighters.get(player.user_id);
    if (existing) return existing;

    const letter = (player.nickname || player.username || "?")[0]?.toUpperCase() || "?";
    const textureKey = await bakeAvatarTexture(this.scene, player.avatar_url, teamColor, letter, TEXTURE_SIZE, player.username);

    const power = player.power ?? POWER_FOR_MIN;
    const diameter = this.diameterFor(power);
    const destination = this.findOpenSpawnPoint(player.team, diameter, dropIn);
    const enterFromCenter = dropIn && this.options.centerEntrance;
    const x = enterFromCenter ? CENTER_X : destination.x;
    const y = enterFromCenter
      ? Math.max(CEILING_Y + 220, this.options.fieldYMin - 100)
      : destination.y;

    const sprite = this.scene.matter.add.sprite(x, y, textureKey, undefined, {
      shape: { type: "circle", radius: diameter / 2 },
      restitution: 0.35,
      friction: 0.2,
      frictionAir: this.options.frictionAir,
      density: 0.002,
    });
    sprite.setDisplaySize(diameter, diameter);
    sprite.setFixedRotation();
    sprite.setDepth(20);

    const hpBarBg = this.scene.add.rectangle(x, y - diameter / 2 - 8, diameter, 7, 0x000000, 0.65).setDepth(24);
    const hpBar = this.scene.add
      .rectangle(x - diameter / 2, y - diameter / 2 - 8, diameter, 5, 0x4ade80)
      .setOrigin(0, 0.5)
      .setDepth(25);
    const powerLabel = this.scene.add
      .text(x, y - diameter / 2 - 22, this.formatPower(power), {
        fontFamily: "Segoe UI, sans-serif",
        fontSize: "18px",
        fontStyle: "bold",
        color: "#ffffff",
        stroke: "#000000",
        strokeThickness: 4,
      })
      .setOrigin(0.5)
      .setDepth(26)
      .setVisible(this.options.showPowerLabel);

    const fighter: Fighter = {
      sprite,
      hpBarBg,
      hpBar,
      powerLabel,
      player,
      power,
      peakPower: power,
      diameter,
      entering: enterFromCenter,
      pendingAttackGrowth: 0,
    };
    this.fighters.set(player.user_id, fighter);
    if (enterFromCenter) this.playCenterEntrance(fighter, destination);
    if (this.options.idleWander) this.startIdleWander(fighter);
    return fighter;
  }

  /** A new tank-war voter is deliberately introduced in the centre at a
   * readable size, then shrinks as it travels to its team. The Matter body is
   * moved with the artwork so it cannot snap back on the next physics tick. */
  private playCenterEntrance(fighter: Fighter, destination: { x: number; y: number }): void {
    const { sprite, diameter } = fighter;
    const body = sprite.body as MatterJS.BodyType | undefined;
    const baseScale = sprite.scale;
    const entryScale = baseScale * (ENTRY_DIAMETER / diameter);
    sprite.setScale(entryScale);
    if (body) (body as any).isSensor = true;

    const path = { x: sprite.x, y: sprite.y };
    this.scene.tweens.add({
      targets: path,
      x: destination.x,
      y: destination.y,
      duration: ENTRY_DURATION_MS,
      ease: "Cubic.easeInOut",
      onUpdate: () => {
        sprite.setPosition(path.x, path.y);
        if (body) this.scene.matter.body.setPosition(body, new Phaser.Math.Vector2(path.x, path.y));
      },
    });
    this.scene.tweens.add({
      targets: sprite,
      scale: baseScale,
      duration: ENTRY_DURATION_MS,
      ease: "Cubic.easeOut",
      onComplete: () => {
        if (!sprite.active) return;
        if (body) {
          (body as any).isSensor = false;
          this.scene.matter.body.setVelocity(body, { x: Phaser.Math.FloatBetween(-0.35, 0.35), y: 0 });
        }
        fighter.entering = false;
        if (fighter.pendingAttackGrowth) {
          const pixels = fighter.pendingAttackGrowth;
          fighter.pendingAttackGrowth = 0;
          this.growOnAttack(fighter.player.user_id, pixels);
        }
      },
    });
  }

  /** Matter makes the army obey the floor and divider. A tiny nudge every few
   * seconds gives the settled circles organic motion without turning them
   * into a chaotic pinball field. */
  private startIdleWander(fighter: Fighter): void {
    fighter.wanderEvent = this.scene.time.addEvent({
      delay: Phaser.Math.Between(1300, 2600),
      loop: true,
      callback: () => {
        if (!fighter.sprite.active || fighter.entering) return;
        const body = fighter.sprite.body as MatterJS.BodyType | undefined;
        if (!body) return;
        const velocity = (body as any).velocity || { x: 0, y: 0 };
        this.scene.matter.body.setVelocity(body, {
          x: Phaser.Math.Clamp(velocity.x + Phaser.Math.FloatBetween(-0.45, 0.45), -0.9, 0.9),
          y: Phaser.Math.Clamp(velocity.y + Phaser.Math.FloatBetween(-0.08, 0.02), -0.22, 0.22),
        });
      },
    });
  }

  /** Finds an empty position before creating the physics body. Matter keeps
   * the circles apart afterwards; this prevents the brief but distracting
   * overlap that occurred when two entrants were assigned the same spot. */
  private findOpenSpawnPoint(team: "A" | "B", diameter: number, dropIn: boolean) {
    const zone = team === "A" ? SIDE_A_ZONE : SIDE_B_ZONE;
    const radius = diameter / 2;
    const xMin = zone.xMin + radius + SPAWN_GAP;
    const xMax = zone.xMax - radius - SPAWN_GAP;
    const fieldYMin = Math.max(CEILING_Y + radius + SPAWN_GAP, this.options.fieldYMin);
    const fieldYMax = Math.max(
      fieldYMin,
      Math.min(arenaLayout.floorY - 200 - radius - SPAWN_GAP, this.options.fieldYMax)
    );
    const yMin = dropIn ? this.options.spawnY : fieldYMin;
    const yMax = dropIn ? this.options.spawnY : fieldYMax;
    let best = { x: (xMin + xMax) / 2, y: yMin, clearance: -Infinity };

    for (let attempt = 0; attempt < SPAWN_POSITION_ATTEMPTS; attempt += 1) {
      const x = Phaser.Math.FloatBetween(xMin, xMax);
      const y = dropIn ? yMin : Phaser.Math.FloatBetween(yMin, yMax);
      let clearance = Infinity;

      for (const fighter of this.fighters.values()) {
        if (fighter.player.team !== team || !fighter.sprite.active) continue;
        const dx = x - fighter.sprite.x;
        const dy = y - fighter.sprite.y;
        const distance = Math.hypot(dx, dy);
        const required = radius + fighter.diameter / 2 + SPAWN_GAP;
        clearance = Math.min(clearance, distance - required);
      }

      if (clearance >= 0) return { x, y };
      if (clearance > best.clearance) best = { x, y, clearance };
    }

    // A full field can leave no completely empty point. Use the least crowded
    // candidate; collisions still keep it from remaining overlapped.
    return best;
  }

  private formatPower(power: number): string {
    return Math.round(power).toLocaleString("pt-BR");
  }

  setPower(userId: string, power: number): void {
    const fighter = this.fighters.get(userId);
    if (!fighter) return;

    fighter.power = Math.max(0, power);
    fighter.peakPower = Math.max(fighter.peakPower, fighter.power);
    fighter.powerLabel.setText(this.formatPower(fighter.power));

    const target = this.diameterFor(fighter.power);
    if (Math.abs(target - fighter.diameter) > 3) {
      this.resize(fighter, target);
    }
  }

  /** Each tank-war shot earns its owner one physical pixel. It is intentionally
   * independent of HP/power: firing feels rewarding even though enemy bombs
   * can later reduce that soldier's health. */
  growOnAttack(userId: string, pixels = 1): void {
    const fighter = this.fighters.get(userId);
    if (!fighter) return;
    if (fighter.entering) {
      fighter.pendingAttackGrowth += pixels;
      return;
    }
    const next = Phaser.Math.Clamp(fighter.diameter + pixels, MIN_DIAMETER, MAX_DIAMETER);
    if (next <= fighter.diameter) return;
    this.resize(fighter, next);
    this.scene.tweens.add({
      targets: fighter.sprite,
      scale: fighter.sprite.scale * 1.08,
      duration: 90,
      yoyo: true,
      ease: "Quad.easeOut",
    });
  }

  private resize(fighter: Fighter, diameter: number): void {
    fighter.diameter = diameter;
    fighter.sprite.setDisplaySize(diameter, diameter);
    // Matter keeps the original circle body, so scale it to match the art.
    const body = fighter.sprite.body as MatterJS.BodyType | undefined;
    if (body) {
      const currentRadius = (body as any).circleRadius || diameter / 2;
      const factor = diameter / 2 / currentRadius;
      if (Number.isFinite(factor) && factor > 0) {
        this.scene.matter.body.scale(body, factor, factor);
        (body as any).circleRadius = diameter / 2;
      }
    }
    fighter.hpBarBg.setSize(diameter, 7);
  }

  /** Growth pop: the avatar swells briefly so a big gift reads instantly. */
  celebrateGrowth(userId: string, leveledUp: boolean): void {
    const fighter = this.fighters.get(userId);
    if (!fighter) return;

    this.scene.tweens.add({
      targets: fighter.sprite,
      scale: fighter.sprite.scale * (leveledUp ? 1.5 : 1.25),
      duration: 160,
      yoyo: true,
      ease: "Quad.easeOut",
    });

    const ring = this.scene.add
      .circle(fighter.sprite.x, fighter.sprite.y, fighter.diameter / 2 + 4, 0xffffff, 0)
      .setStrokeStyle(3, leveledUp ? 0xffd700 : 0x7dd3fc, 0.9)
      .setDepth(23);
    this.scene.tweens.add({
      targets: ring,
      scale: 1.8,
      alpha: 0,
      duration: 420,
      onComplete: () => ring.destroy(),
    });
  }

  eliminate(userId: string): void {
    const fighter = this.fighters.get(userId);
    if (!fighter) return;

    fighter.power = 0;
    this.scene.tweens.add({
      targets: [fighter.sprite, fighter.powerLabel, fighter.hpBar, fighter.hpBarBg],
      alpha: 0,
      scale: 0.2,
      duration: 420,
      ease: "Back.easeIn",
      onComplete: () => this.destroyFighter(userId),
    });
  }

  private destroyFighter(userId: string): void {
    const fighter = this.fighters.get(userId);
    if (!fighter) return;
    fighter.wanderEvent?.remove(false);
    fighter.sprite.destroy();
    fighter.hpBar.destroy();
    fighter.hpBarBg.destroy();
    fighter.powerLabel.destroy();
    this.fighters.delete(userId);
  }

  /** Keeps the HP bar and power label glued to their bouncing avatar. */
  syncOverlays(): void {
    for (const fighter of this.fighters.values()) {
      const { sprite, diameter } = fighter;
      const top = sprite.y - diameter / 2 - 8;
      fighter.hpBarBg.setPosition(sprite.x, top);
      fighter.hpBar.setPosition(sprite.x - diameter / 2 + 1, top);
      fighter.powerLabel.setPosition(sprite.x, top - 14);

      const pct = Phaser.Math.Clamp(fighter.power / Math.max(1, fighter.peakPower), 0, 1);
      fighter.hpBar.width = Math.max(1, (diameter - 2) * pct);
      fighter.hpBar.fillColor = pct <= 0.25 ? 0xef4444 : pct <= 0.6 ? 0xfacc15 : 0x4ade80;
    }
  }

  removeStale(activeUserIds: Set<string>): void {
    for (const userId of Array.from(this.fighters.keys())) {
      if (!activeUserIds.has(userId)) this.destroyFighter(userId);
    }
  }
}
