import Phaser from "phaser";
import type { EffectsManager } from "./EffectsManager";

export class HealManager {
  private scene: Phaser.Scene;
  private effects: EffectsManager;

  constructor(scene: Phaser.Scene, effects: EffectsManager) {
    this.scene = scene;
    this.effects = effects;
  }

  /** Heal travels from the sender's ball to the character as hearts +
   * sparkles, then shows +XP on arrival (spec section 16). */
  fireHeal(fromX: number, fromY: number, toX: number, toY: number, big: boolean, onImpact: () => void) {
    const count = big ? 6 : 3;
    for (let i = 0; i < count; i++) {
      const heart = this.scene.add
        .text(fromX + Phaser.Math.Between(-12, 12), fromY + Phaser.Math.Between(-12, 12), big ? "💚" : "❤️", {
          fontSize: big ? "34px" : "24px",
        })
        .setOrigin(0.5)
        .setDepth(55);

      this.scene.tweens.add({
        targets: heart,
        x: toX + Phaser.Math.Between(-20, 20),
        y: toY + Phaser.Math.Between(-20, 20),
        duration: 500 + i * 40,
        delay: i * 60,
        ease: "Sine.easeInOut",
        onComplete: () => {
          heart.destroy();
          this.effects.burst(toX, toY, 0x66ffb2, big ? 22 : 12, 150);
          if (i === count - 1) {
            this.effects.flash(toX, toY, big ? 70 : 45, 0x66ffb2, 0.7);
            onImpact();
          }
        },
      });
    }
  }
}
