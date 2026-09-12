import Phaser from "phaser";
import type { PlayerPayload } from "../../../types/events";
import { bakeAvatarTexture } from "../avatarTexture";
import {
  ARENA_WIDTH,
  AVATAR_DIAMETER,
  AVATAR_DIAMETER_GIANT,
  CEILING_Y,
  FLOOR_Y,
  SIDE_A_ZONE,
  SIDE_B_ZONE,
  SPAWN_TOP_Y,
} from "../constants";

export interface AvatarEntry {
  body: Phaser.Physics.Matter.Sprite;
  ring: Phaser.GameObjects.Arc;
  label: Phaser.GameObjects.Text | null;
  player: PlayerPayload;
  giant: boolean;
}

export class AvatarManager {
  private scene: Phaser.Scene;
  private avatars = new Map<string, AvatarEntry>();

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
  }

  has(userId: string): boolean {
    return this.avatars.has(userId);
  }

  get(userId: string): AvatarEntry | undefined {
    return this.avatars.get(userId);
  }

  all(): AvatarEntry[] {
    return Array.from(this.avatars.values());
  }

  async spawnOrGet(player: PlayerPayload, teamColor: string, dropIn = true): Promise<AvatarEntry> {
    const existing = this.avatars.get(player.user_id);
    if (existing) return existing;

    const letter = (player.nickname || player.username || "?")[0]?.toUpperCase() || "?";
    const textureKey = await bakeAvatarTexture(this.scene, player.avatar_url, teamColor, letter, AVATAR_DIAMETER);

    const zone = player.team === "A" ? SIDE_A_ZONE : SIDE_B_ZONE;
    const x = Phaser.Math.Between(zone.xMin + AVATAR_DIAMETER, zone.xMax - AVATAR_DIAMETER);
    const y = dropIn ? SPAWN_TOP_Y : Phaser.Math.Between(CEILING_Y, FLOOR_Y - 200);

    const sprite = this.scene.matter.add.sprite(x, y, textureKey, undefined, {
      shape: { type: "circle", radius: AVATAR_DIAMETER / 2 },
      restitution: 0.45,
      friction: 0.15,
      frictionAir: 0.012,
      density: 0.0018,
    });
    sprite.setDisplaySize(AVATAR_DIAMETER, AVATAR_DIAMETER);
    sprite.setBounce(0.4);
    sprite.setFixedRotation();
    sprite.setDepth(20);

    const entry: AvatarEntry = { body: sprite, ring: null as any, label: null, player, giant: false };
    this.avatars.set(player.user_id, entry);
    return entry;
  }

  updatePlayerMeta(player: PlayerPayload) {
    const entry = this.avatars.get(player.user_id);
    if (entry) entry.player = player;
  }

  highlight(userId: string) {
    const entry = this.avatars.get(userId);
    if (!entry) return;
    const sprite = entry.body;
    this.scene.tweens.add({
      targets: sprite,
      scale: sprite.scale * 1.35,
      duration: 120,
      yoyo: true,
      ease: "Quad.easeOut",
    });
    const flash = this.scene.add.circle(sprite.x, sprite.y, AVATAR_DIAMETER / 2 + 6, 0xffffff, 0.6);
    flash.setDepth(21);
    this.scene.tweens.add({
      targets: flash,
      alpha: 0,
      scale: 1.6,
      duration: 260,
      onComplete: () => flash.destroy(),
    });
  }

  makeGiant(userId: string, durationMs = 6000) {
    const entry = this.avatars.get(userId);
    if (!entry || entry.giant) return;
    entry.giant = true;
    const sprite = entry.body;
    const scaleFactor = AVATAR_DIAMETER_GIANT / AVATAR_DIAMETER;
    this.scene.tweens.add({ targets: sprite, scale: sprite.scale * scaleFactor, duration: 300 });
    sprite.setMass(sprite.body ? (sprite.body as MatterJS.BodyType).mass * 6 : 1);

    this.scene.time.delayedCall(durationMs, () => {
      if (!entry.body.active) return;
      this.scene.tweens.add({ targets: sprite, scale: sprite.scale / scaleFactor, duration: 300 });
      entry.giant = false;
    });
  }

  removeStale(activeUserIds: Set<string>) {
    for (const [userId, entry] of this.avatars.entries()) {
      if (!activeUserIds.has(userId)) {
        entry.body.destroy();
        entry.label?.destroy();
        this.avatars.delete(userId);
      }
    }
  }

  applyRadialForce(originX: number, originY: number, strength: number, radius: number) {
    for (const entry of this.avatars.values()) {
      const sprite = entry.body;
      const dx = sprite.x - originX;
      const dy = sprite.y - originY;
      const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      if (dist > radius) continue;
      const falloff = 1 - dist / radius;
      const fx = (dx / dist) * strength * falloff;
      const fy = (dy / dist) * strength * falloff;
      sprite.applyForce(new Phaser.Math.Vector2(fx, fy));
    }
  }

  spinAll(torque: number) {
    for (const entry of this.avatars.values()) {
      const body = entry.body.body as MatterJS.BodyType | undefined;
      if (body) this.scene.matter.body.setAngularVelocity(body, torque);
    }
  }
}
