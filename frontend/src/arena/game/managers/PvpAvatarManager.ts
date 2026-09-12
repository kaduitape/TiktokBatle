import Phaser from "phaser";
import type { PvpPlayerPayload } from "../../../types/events";
import { bakeAvatarTexture } from "../avatarTexture";
import { CEILING_Y, FLOOR_Y, SIDE_A_ZONE, SIDE_B_ZONE, SPAWN_TOP_Y } from "../constants";

const TEXTURE_SIZE = 128;
const MIN_DIAMETER = 46;
const MAX_DIAMETER = 190;
const POWER_FOR_MIN = 100;

export interface Fighter {
  sprite: Phaser.Physics.Matter.Sprite;
  hpBarBg: Phaser.GameObjects.Rectangle;
  hpBar: Phaser.GameObjects.Rectangle;
  powerLabel: Phaser.GameObjects.Text;
  player: PvpPlayerPayload;
  power: number;
  peakPower: number;
  diameter: number;
}

/** Sizes every fighter by its own power, the way the reference battles do:
 * a viewer who keeps feeding gifts visibly outgrows everyone else, and the
 * bar above the avatar drains as enemies chip that power away. */
export class PvpAvatarManager {
  private scene: Phaser.Scene;
  private fighters = new Map<string, Fighter>();

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
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
    const ratio = Math.max(1, power / POWER_FOR_MIN);
    const diameter = MIN_DIAMETER + Math.log2(ratio) * 26;
    return Phaser.Math.Clamp(diameter, MIN_DIAMETER, MAX_DIAMETER);
  }

  async spawnOrGet(player: PvpPlayerPayload, teamColor: string, dropIn = true): Promise<Fighter> {
    const existing = this.fighters.get(player.user_id);
    if (existing) return existing;

    const letter = (player.nickname || player.username || "?")[0]?.toUpperCase() || "?";
    const textureKey = await bakeAvatarTexture(this.scene, player.avatar_url, teamColor, letter, TEXTURE_SIZE);

    const power = player.power ?? POWER_FOR_MIN;
    const diameter = this.diameterFor(power);
    const zone = player.team === "A" ? SIDE_A_ZONE : SIDE_B_ZONE;
    const x = Phaser.Math.Between(zone.xMin + diameter, zone.xMax - diameter);
    const y = dropIn ? SPAWN_TOP_Y : Phaser.Math.Between(CEILING_Y, FLOOR_Y - 200);

    const sprite = this.scene.matter.add.sprite(x, y, textureKey, undefined, {
      shape: { type: "circle", radius: diameter / 2 },
      restitution: 0.35,
      friction: 0.2,
      frictionAir: 0.015,
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
      .setDepth(26);

    const fighter: Fighter = {
      sprite,
      hpBarBg,
      hpBar,
      powerLabel,
      player,
      power,
      peakPower: power,
      diameter,
    };
    this.fighters.set(player.user_id, fighter);
    return fighter;
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
