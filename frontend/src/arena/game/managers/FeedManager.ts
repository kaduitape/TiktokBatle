import Phaser from "phaser";
import { FEED_Y } from "../constants";

const MAX_LINES = 5;
const LINE_HEIGHT = 26;

export class FeedManager {
  private scene: Phaser.Scene;
  private lines: Phaser.GameObjects.Text[] = [];

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
  }

  /** Small scrolling feed of the latest interactions -- deliberately
   * compact (spec section 35: "não ocupar grande parte da arena"). */
  push(text: string) {
    const label = this.scene.add
      .text(24, FEED_Y + MAX_LINES * LINE_HEIGHT, text, {
        fontFamily: "Segoe UI, sans-serif",
        fontSize: "18px",
        color: "#ffffff",
        stroke: "#000",
        strokeThickness: 3,
      })
      .setDepth(88)
      .setAlpha(0);

    this.lines.push(label);
    this.scene.tweens.add({ targets: label, alpha: 1, duration: 150 });

    if (this.lines.length > MAX_LINES) {
      const removed = this.lines.shift();
      removed?.destroy();
    }

    this.lines.forEach((line, idx) => {
      const targetY = FEED_Y + idx * LINE_HEIGHT;
      this.scene.tweens.add({ targets: line, y: targetY, duration: 220, ease: "Cubic.easeOut" });
    });

    this.scene.time.delayedCall(6000, () => {
      if (!label.active) return;
      this.scene.tweens.add({
        targets: label,
        alpha: 0,
        duration: 300,
        onComplete: () => {
          const idx = this.lines.indexOf(label);
          if (idx >= 0) this.lines.splice(idx, 1);
          label.destroy();
        },
      });
    });
  }
}
