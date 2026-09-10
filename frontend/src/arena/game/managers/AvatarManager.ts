import Phaser from "phaser";
import { API_BASE } from "../../../api/client";
import type { PlayerPayload } from "../../../types/events";
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

const PLACEHOLDER_COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#f1c40f", "#9b59b6", "#1abc9c", "#e67e22"];

function resolveUrl(url: string | null): string | null {
  if (!url) return null;
  if (url.startsWith("http") || url.startsWith("data:")) return url;
  return `${API_BASE}${url}`;
}

function hashKey(input: string): string {
  let h = 0;
  for (let i = 0; i < input.length; i++) {
    h = (h << 5) - h + input.charCodeAt(i);
    h |= 0;
  }
  return `av_${Math.abs(h)}`;
}

export class AvatarManager {
  private scene: Phaser.Scene;
  private avatars = new Map<string, AvatarEntry>();
  private pendingBake = new Set<string>();

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

  /** Bakes a circular, ring-bordered texture once per (avatar url, team color)
   * so runtime rendering is a single cheap Matter sprite per avatar --
   * no per-frame masking needed even with hundreds on screen. */
  private async bakeTexture(url: string | null, teamColor: string, fallbackLetter: string): Promise<string> {
    const textureKey = hashKey(`${url || "placeholder"}_${teamColor}`);
    if (this.scene.textures.exists(textureKey)) return textureKey;
    if (this.pendingBake.has(textureKey)) {
      await new Promise((r) => setTimeout(r, 60));
      return this.scene.textures.exists(textureKey) ? textureKey : this.bakeTexture(url, teamColor, fallbackLetter);
    }
    this.pendingBake.add(textureKey);

    const size = AVATAR_DIAMETER;
    const resolved = resolveUrl(url);

    try {
      if (resolved) {
        await new Promise<void>((resolve, reject) => {
          const loaderKey = `${textureKey}_raw`;
          if (this.scene.textures.exists(loaderKey)) return resolve();
          this.scene.load.setCORS("anonymous");
          this.scene.load.image(loaderKey, resolved);
          this.scene.load.once(`filecomplete-image-${loaderKey}`, () => resolve());
          this.scene.load.once("loaderror", () => reject(new Error("avatar load failed")));
          this.scene.load.start();
        });
        this.compositeCircularTexture(textureKey, `${textureKey}_raw`, size, teamColor);
      } else {
        this.compositeFallbackTexture(textureKey, size, teamColor, fallbackLetter);
      }
    } catch {
      this.compositeFallbackTexture(textureKey, size, teamColor, fallbackLetter);
    }

    this.pendingBake.delete(textureKey);
    return textureKey;
  }

  private compositeCircularTexture(key: string, sourceKey: string, size: number, ringColor: string) {
    const rt = this.scene.make.renderTexture({ width: size, height: size }, false);
    const maskShape = this.scene.make.graphics({}, false);
    maskShape.fillStyle(0xffffff);
    maskShape.fillCircle(size / 2, size / 2, size / 2 - 3);
    rt.setMask(maskShape.createGeometryMask());

    const img = this.scene.make.image({ key: sourceKey }, false);
    const scale = size / Math.min(img.width, img.height);
    img.setScale(scale).setPosition(size / 2, size / 2);
    rt.draw(img, size / 2, size / 2);
    rt.clearMask();

    const ring = this.scene.make.graphics({}, false);
    const color = Phaser.Display.Color.HexStringToColor(ringColor).color;
    ring.lineStyle(4, color, 1);
    ring.strokeCircle(size / 2, size / 2, size / 2 - 2);
    rt.draw(ring, 0, 0);

    rt.saveTexture(key);
    rt.destroy();
    maskShape.destroy();
    ring.destroy();
    img.destroy();
  }

  private compositeFallbackTexture(key: string, size: number, ringColor: string, letter: string) {
    const bg = PLACEHOLDER_COLORS[Math.abs(hashCode(letter)) % PLACEHOLDER_COLORS.length];
    const g = this.scene.make.graphics({}, false);
    g.fillStyle(Phaser.Display.Color.HexStringToColor(bg).color);
    g.fillCircle(size / 2, size / 2, size / 2 - 3);
    const color = Phaser.Display.Color.HexStringToColor(ringColor).color;
    g.lineStyle(4, color, 1);
    g.strokeCircle(size / 2, size / 2, size / 2 - 2);
    g.generateTexture(key, size, size);
    g.destroy();
  }

  async spawnOrGet(player: PlayerPayload, teamColor: string, dropIn = true): Promise<AvatarEntry> {
    const existing = this.avatars.get(player.user_id);
    if (existing) return existing;

    const letter = (player.nickname || player.username || "?")[0]?.toUpperCase() || "?";
    const textureKey = await this.bakeTexture(player.avatar_url, teamColor, letter);

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

function hashCode(str: string): number {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h << 5) - h + str.charCodeAt(i);
  return h;
}
