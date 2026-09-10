import Phaser from "phaser";
import type { EffectsManager } from "./EffectsManager";

interface Pooled {
  obj: Phaser.GameObjects.Arc;
  inUse: boolean;
}

const POOL_SIZE = 60;

export class ProjectileManager {
  private scene: Phaser.Scene;
  private effects: EffectsManager;
  private pool: Pooled[] = [];

  constructor(scene: Phaser.Scene, effects: EffectsManager) {
    this.scene = scene;
    this.effects = effects;
    for (let i = 0; i < POOL_SIZE; i++) {
      const obj = scene.add.circle(0, 0, 7, 0xffe066).setDepth(50).setVisible(false);
      this.pool.push({ obj, inUse: false });
    }
  }

  private acquire(): Pooled | null {
    return this.pool.find((p) => !p.inUse) || null;
  }

  /** A single shot projectile travelling from the shooter's ball to the
   * target character, ending in a small impact + damage number
   * (spec section 14). */
  fireShot(fromX: number, fromY: number, toX: number, toY: number, onImpact: () => void, delayMs = 0) {
    this.scene.time.delayedCall(delayMs, () => {
      const p = this.acquire();
      if (!p) return;
      p.inUse = true;
      p.obj.setPosition(fromX, fromY).setVisible(true).setAlpha(1).setFillStyle(0xffe066);

      this.effects.flash(fromX, fromY, 14, 0xffffff, 0.7);

      const dist = Phaser.Math.Distance.Between(fromX, fromY, toX, toY);
      const duration = Phaser.Math.Clamp(dist * 0.9, 140, 420);

      this.scene.tweens.add({
        targets: p.obj,
        x: toX,
        y: toY,
        duration,
        ease: "Cubic.easeIn",
        onComplete: () => {
          p.obj.setVisible(false);
          p.inUse = false;
          this.effects.flash(toX, toY, 22, 0xff5b5b, 0.85);
          this.effects.burst(toX, toY, 0xffcc55, 10, 140);
          onImpact();
        },
      });
    });
  }

  /** RAJADA/METRALHADORA: several shots fired in quick succession from the
   * same avatar (spec sections 17-18), aggregated so 100 gifts never spawn
   * 100 independent full-weight projectiles. */
  fireBurst(fromX: number, fromY: number, toX: number, toY: number, count: number, onEachImpact: () => void) {
    const visualShots = Math.min(count, 8);
    for (let i = 0; i < visualShots; i++) {
      this.fireShot(
        fromX + Phaser.Math.Between(-8, 8),
        fromY + Phaser.Math.Between(-8, 8),
        toX + Phaser.Math.Between(-16, 16),
        toY + Phaser.Math.Between(-16, 16),
        onEachImpact,
        i * 70
      );
    }
  }
}
