import Phaser from "phaser";
import type { PvpPlayerPayload } from "../../../types/events";
import { bakeAvatarTexture } from "../avatarTexture";
import { layoutNameLabels } from "../nameLabels";
import { arenaLayout, CEILING_Y, CENTER_X, SIDE_A_ZONE, SIDE_B_ZONE, SPAWN_TOP_Y } from "../constants";

// Baked at more than twice the smallest on-screen size so the circle stays
// crisp, and never below it, which is what made small avatars look ragged.
const TEXTURE_SIZE = 160;
const MIN_DIAMETER = 64;

/** How small a packed soldier may get. Below this a face stops being a face,
 * and a wall of dots is worse than a crowd that slightly overlaps. */
const PACKED_MIN_DIAMETER = 26;

/** Circles never tile perfectly and the band is not a perfect rectangle, so
 * only part of it is really usable. Measured against a full field rather than
 * derived: at 1.0 the army fills every pixel and looks like a solid block. */
const PACKING_EFFICIENCY = 0.55;
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
  nameLabel: Phaser.GameObjects.Text;
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
  /** Shrink everybody as their side fills up, so a full army still fits in
   * its band instead of being squeezed out past the arena's edges. Only the
   * modes with a fixed soldier size use it; PvP sizes by power instead. */
  packToFit?: boolean;
}

/** Manages the circular avatars that fight in the arena: an HP bar that
 * drains above each one, and (in PvP) a diameter that grows with the
 * owner's power, the way the reference battles do. */
/** The viewer's name, drawn under their photo: white with a black shadow so
 * it stays readable over any arena background. */
const NAME_STYLE: Phaser.Types.GameObjects.Text.TextStyle = {
  fontFamily: "Segoe UI, sans-serif",
  fontSize: "18px",
  fontStyle: "bold",
  color: "#ffffff",
  stroke: "#000000",
  strokeThickness: 4,
  shadow: { offsetX: 0, offsetY: 2, color: "#000000", blur: 4, fill: true },
};

/** Long handles would cover the neighbours; trim rather than shrink, so every
 * name stays the same readable size. */
function displayName(player: PvpPlayerPayload): string {
  const raw = (player.nickname || player.username || "").trim();
  return raw.length > 12 ? `${raw.slice(0, 11)}…` : raw;
}

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
      packToFit: options.packToFit ?? false,
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
  /** Re-bake and swap the sprite's texture when the person's photo changed. */
  private async refreshTexture(
    fighter: Fighter,
    player: PvpPlayerPayload,
    teamColor: string,
  ): Promise<void> {
    const current = fighter.player.avatar_url ?? null;
    const next = player.avatar_url ?? null;
    fighter.nameLabel.setText(displayName(player));
    if (next === current) {
      fighter.player = player;
      return;
    }

    const letter = (player.nickname || player.username || "?")[0]?.toUpperCase() || "?";
    const textureKey = await bakeAvatarTexture(
      this.scene,
      next,
      teamColor,
      letter,
      TEXTURE_SIZE,
      player.username,
    );
    // The fighter may have been eliminated while the texture was baking.
    if (!this.fighters.has(player.user_id) || !fighter.sprite.active) return;
    fighter.sprite.setTexture(textureKey);
    fighter.sprite.setDisplaySize(fighter.diameter, fighter.diameter);
    fighter.player = player;
  }

  /** The size everybody on one side should be, given how many of them there
   * are. Returns the normal size until the band actually runs out of room. */
  private packedDiameter(team: "A" | "B"): number {
    return this.packedDiameterFor(team, 0);
  }

  private packedDiameterFor(team: "A" | "B", extra: number): number {
    if (!this.options.packToFit) return MIN_DIAMETER;

    const zone = team === "A" ? SIDE_A_ZONE : SIDE_B_ZONE;
    const width = Math.max(1, zone.xMax - zone.xMin);
    const top = Math.max(CEILING_Y, this.options.fieldYMin ?? CEILING_Y);
    const bottom = Math.min(arenaLayout.floorY, this.options.fieldYMax ?? arenaLayout.floorY);
    const height = Math.max(1, bottom - top);

    const count =
      this.all().filter((f) => f.player.team === team && f.sprite.active).length + extra;
    if (count <= 1) return MIN_DIAMETER;

    const perSoldier = (width * height * PACKING_EFFICIENCY) / count;
    const fits = Math.sqrt(perSoldier) - SPAWN_GAP;
    return Phaser.Math.Clamp(fits, PACKED_MIN_DIAMETER, MIN_DIAMETER);
  }

  /** Resize a side after somebody joined or left, so the whole army changes
   * together instead of newcomers arriving smaller than everybody else. */
  private repackSide(team: "A" | "B"): void {
    if (!this.options.packToFit) return;
    const target = this.packedDiameter(team);

    for (const fighter of this.fighters.values()) {
      if (fighter.player.team !== team || !fighter.sprite.active) continue;
      if (Math.abs(fighter.diameter - target) < 1) continue;

      const ratio = target / fighter.diameter;
      const body = fighter.sprite.body as MatterJS.BodyType | undefined;
      if (body) this.scene.matter.body.scale(body, ratio, ratio);
      fighter.sprite.setDisplaySize(target, target);
      fighter.diameter = target;
    }
  }

  private diameterFor(power: number): number {
    if (!this.options.scaleWithPower) return MIN_DIAMETER;
    const ratio = Math.max(1, power / POWER_FOR_MIN);
    const diameter = MIN_DIAMETER + Math.log2(ratio) * 26;
    return Phaser.Math.Clamp(diameter, MIN_DIAMETER, MAX_DIAMETER);
  }

  async spawnOrGet(player: PvpPlayerPayload, teamColor: string, dropIn = true): Promise<Fighter> {
    const existing = this.fighters.get(player.user_id);
    if (existing) {
      // Same reason as AvatarManager: a photo that arrives after the fighter
      // did would otherwise never be drawn.
      await this.refreshTexture(existing, player, teamColor);
      return existing;
    }

    const letter = (player.nickname || player.username || "?")[0]?.toUpperCase() || "?";
    const textureKey = await bakeAvatarTexture(this.scene, player.avatar_url, teamColor, letter, TEXTURE_SIZE, player.username);

    const power = player.power ?? POWER_FOR_MIN;
    // Count this newcomer before sizing, so they arrive at the size the side
    // is about to settle on rather than one step behind it.
    const diameter = this.options.packToFit
      ? this.packedDiameterFor(player.team, 1)
      : this.diameterFor(power);
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
    if (this.options.packToFit) {
      // Gravity dragged the whole army into one line along the floor, where a
      // side's worth of soldiers is wider than its half of the arena and the
      // physics pushed the ends out past the edges. Held in place they keep
      // the spread that findOpenSpawnPoint gave them and fill the band.
      sprite.setIgnoreGravity(true);
    }

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

    const nameLabel = this.scene.add
      .text(x, y + diameter / 2 + 3, displayName(player), NAME_STYLE)
      .setOrigin(0.5, 0)
      .setDepth(26);

    const fighter: Fighter = {
      sprite,
      hpBarBg,
      hpBar,
      nameLabel,
      powerLabel,
      player,
      power,
      peakPower: power,
      diameter,
      entering: enterFromCenter,
      pendingAttackGrowth: 0,
    };
    this.fighters.set(player.user_id, fighter);
    // Everybody on this side shrinks together, so nobody is left oversized.
    this.repackSide(player.team);
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
    // A held army has nothing to settle it, so an arrival must be given a real
    // place in the band. Left at the entrance height it simply stayed there,
    // and newcomers piled into a line under the troops instead of joining them.
    const placeInField = !dropIn || this.options.packToFit;
    const yMin = placeInField ? fieldYMin : this.options.spawnY;
    const yMax = placeInField ? fieldYMax : this.options.spawnY;
    let best = { x: (xMin + xMax) / 2, y: yMin, clearance: -Infinity };

    for (let attempt = 0; attempt < SPAWN_POSITION_ATTEMPTS; attempt += 1) {
      const x = Phaser.Math.FloatBetween(xMin, xMax);
      const y = placeInField ? Phaser.Math.FloatBetween(yMin, yMax) : yMin;
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
    // Room freed by a casualty goes back to the survivors.
    const leaving = this.fighters.get(userId);
    const fighter = this.fighters.get(userId);
    if (!fighter) return;
    fighter.wanderEvent?.remove(false);
    fighter.sprite.destroy();
    fighter.hpBar.destroy();
    fighter.hpBarBg.destroy();
    fighter.powerLabel.destroy();
    fighter.nameLabel.destroy();
    this.fighters.delete(userId);
    if (leaving) this.repackSide(leaving.player.team);
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

    // Names are placed together, after the bars: a packed arena puts several
    // avatars side by side, and each name centred under its own would overlap
    // the next into an unreadable smudge.
    layoutNameLabels(
      this.all()
        .filter((f) => f.sprite.active)
        .map((f) => ({
          label: f.nameLabel,
          x: f.sprite.x,
          y: f.sprite.y + f.diameter / 2 + 4,
          // Clear of the HP bar, which sits 8px above the avatar.
          yAbove: f.sprite.y - f.diameter / 2 - 26,
        })),
    );
  }

  removeStale(activeUserIds: Set<string>): void {
    for (const userId of Array.from(this.fighters.keys())) {
      if (!activeUserIds.has(userId)) this.destroyFighter(userId);
    }
  }
}
