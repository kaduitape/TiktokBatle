import Phaser from "phaser";
import type { EffectsManager } from "./EffectsManager";

export class MissileManager {
  private scene: Phaser.Scene;
  private effects: EffectsManager;

  constructor(scene: Phaser.Scene, effects: EffectsManager) {
    this.scene = scene;
    this.effects = effects;
  }

  /** Missile arcs from the sender's ball to the target character with a
   * smoke trail, then detonates with a bigger explosion + camera shake
   * (spec section 15). */
  fireMissile(fromX: number, fromY: number, toX: number, toY: number, big: boolean, onImpact: () => void) {
    const icon = this.scene.add
      .text(fromX, fromY, "🚀", { fontSize: big ? "48px" : "34px" })
      .setOrigin(0.5)
      .setDepth(55);

    const midX = (fromX + toX) / 2;
    const midY = Math.min(fromY, toY) - 220;
    const angle = Phaser.Math.Angle.Between(fromX, fromY, toX, toY);
    icon.setRotation(angle + Math.PI / 2);

    const path = new Phaser.Curves.QuadraticBezier(
      new Phaser.Math.Vector2(fromX, fromY),
      new Phaser.Math.Vector2(midX, midY),
      new Phaser.Math.Vector2(toX, toY)
    );

    const smokeTimer = this.scene.time.addEvent({
      delay: 40,
      loop: true,
      callback: () => this.effects.burst(icon.x, icon.y, 0x888888, 2, 30),
    });

    const duration = big ? 900 : 650;
    const tweenObj = { t: 0 };
    this.scene.tweens.add({
      targets: tweenObj,
      t: 1,
      duration,
      ease: "Sine.easeInOut",
      onUpdate: () => {
        const p = path.getPoint(tweenObj.t);
        icon.setPosition(p.x, p.y);
      },
      onComplete: () => {
        smokeTimer.remove();
        icon.destroy();
        this.detonate(toX, toY, big);
        onImpact();
      },
    });
  }

  private detonate(x: number, y: number, big: boolean) {
    this.effects.flash(x, y, big ? 90 : 60, 0xff9933, 0.9);
    this.effects.burst(x, y, 0xff6633, big ? 40 : 24, big ? 320 : 220);
    this.effects.shake(big ? 0.018 : 0.01, big ? 260 : 180);

    const boom = this.scene.add.text(x, y, "💥", { fontSize: big ? "72px" : "48px" }).setOrigin(0.5).setDepth(72);
    this.scene.tweens.add({
      targets: boom,
      scale: 1.4,
      alpha: 0,
      duration: 420,
      onComplete: () => boom.destroy(),
    });
  }

  /** Section 20: an airplane crosses the screen and drops bombs. */
  airstrike(y: number, targetX: number, onImpact: () => void) {
    const plane = this.scene.add.text(-60, y, "✈️", { fontSize: "44px" }).setOrigin(0.5).setDepth(58);
    this.scene.tweens.add({
      targets: plane,
      x: 1140,
      duration: 1800,
      ease: "Linear",
      onUpdate: (tween) => {
        const progress = tween.progress;
        if (progress > 0.35 && progress < 0.75 && Math.random() < 0.05) {
          this.dropBomb(plane.x, plane.y, targetX);
        }
      },
      onComplete: () => {
        plane.destroy();
        onImpact();
      },
    });
  }

  private dropBomb(x: number, y: number, floorTargetX: number) {
    const bomb = this.scene.add.text(x, y, "💣", { fontSize: "30px" }).setOrigin(0.5).setDepth(57);
    const targetY = y + 260;
    this.scene.tweens.add({
      targets: bomb,
      y: targetY,
      x: floorTargetX + Phaser.Math.Between(-60, 60),
      duration: 500,
      ease: "Cubic.easeIn",
      onComplete: () => {
        this.detonate(bomb.x, bomb.y, false);
        bomb.destroy();
      },
    });
  }

  /** Section 21: METEORO -- a big impact event crossing the arena. */
  meteor(targetX: number, targetY: number, onImpact: () => void) {
    const meteor = this.scene.add.text(targetX - 300, -80, "☄️", { fontSize: "64px" }).setOrigin(0.5).setDepth(58);
    this.scene.tweens.add({
      targets: meteor,
      x: targetX,
      y: targetY,
      duration: 750,
      ease: "Cubic.easeIn",
      onComplete: () => {
        meteor.destroy();
        this.detonate(targetX, targetY, true);
        onImpact();
      },
    });
  }

  /** Section 22: RAIO -- a lightning bolt strikes the character. */
  lightning(targetX: number, targetY: number, onImpact: () => void) {
    const bolt = this.scene.add.text(targetX, targetY - 260, "⚡", { fontSize: "80px" }).setOrigin(0.5).setDepth(58).setAlpha(0);
    this.scene.tweens.add({
      targets: bolt,
      alpha: 1,
      y: targetY,
      duration: 140,
      ease: "Cubic.easeIn",
      onComplete: () => {
        this.effects.flash(targetX, targetY, 100, 0xfff2a8, 0.9);
        this.effects.shake(0.02, 200);
        this.scene.time.delayedCall(90, () => bolt.destroy());
        onImpact();
      },
    });
  }
}
