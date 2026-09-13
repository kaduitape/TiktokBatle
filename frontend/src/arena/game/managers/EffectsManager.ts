import Phaser from "phaser";

const MAX_PARTICLES = 260;

export class EffectsManager {
  private scene: Phaser.Scene;
  private dotTextureKey = "fx_dot";
  private emitter: Phaser.GameObjects.Particles.ParticleEmitter | null = null;
  private activeParticles = 0;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
    if (!scene.textures.exists(this.dotTextureKey)) {
      const g = scene.make.graphics({}, false);
      g.fillStyle(0xffffff, 1);
      g.fillCircle(6, 6, 6);
      g.generateTexture(this.dotTextureKey, 12, 12);
      g.destroy();
    }
    this.emitter = scene.add.particles(0, 0, this.dotTextureKey, {
      emitting: false,
      lifespan: 500,
      speed: { min: 60, max: 220 },
      scale: { start: 0.9, end: 0 },
      alpha: { start: 1, end: 0 },
      quantity: 0,
    });
    this.emitter.setDepth(60);
  }

  private budget(n: number): number {
    const allowed = Math.max(0, MAX_PARTICLES - this.activeParticles);
    return Math.min(n, allowed);
  }

  burst(x: number, y: number, color: number, count = 14, speed = 180) {
    const n = this.budget(count);
    if (n <= 0 || !this.emitter) return;
    this.emitter.setParticleTint(color);
    this.emitter.setConfig({ speed: { min: speed * 0.3, max: speed } } as any);
    this.emitter.emitParticleAt(x, y, n);
    this.activeParticles += n;
    this.scene.time.delayedCall(520, () => (this.activeParticles = Math.max(0, this.activeParticles - n)));
  }

  flash(x: number, y: number, radius: number, color = 0xffffff, alpha = 0.8) {
    const circle = this.scene.add.circle(x, y, radius, color, alpha).setDepth(65);
    this.scene.tweens.add({
      targets: circle,
      alpha: 0,
      scale: 2.2,
      duration: 260,
      onComplete: () => circle.destroy(),
    });
  }

  shake(intensity = 0.01, duration = 180) {
    this.scene.cameras.main.shake(duration, intensity);
  }

  floatingNumber(x: number, y: number, text: string, color: string) {
    const label = this.scene.add
      .text(x, y, text, {
        fontFamily: "Segoe UI, sans-serif",
        fontSize: "34px",
        fontStyle: "bold",
        color,
        stroke: "#000000",
        strokeThickness: 5,
      })
      .setOrigin(0.5)
      .setDepth(70);

    this.scene.tweens.add({
      targets: label,
      y: y - 70,
      alpha: 0,
      duration: 900,
      ease: "Cubic.easeOut",
      onComplete: () => label.destroy(),
    });
  }

  bannerText(text: string, x: number, y: number, color = "#ff5b5b", size = 46) {
    const label = this.scene.add
      .text(x, y, text, {
        fontFamily: "Segoe UI, sans-serif",
        fontSize: `${size}px`,
        fontStyle: "bold",
        color,
        stroke: "#000",
        strokeThickness: 6,
      })
      .setOrigin(0.5)
      .setDepth(80)
      .setScale(0.4)
      .setAlpha(0);

    this.scene.tweens.add({
      targets: label,
      scale: 1,
      alpha: 1,
      duration: 220,
      ease: "Back.easeOut",
      onComplete: () => {
        this.scene.time.delayedCall(1100, () => {
          this.scene.tweens.add({
            targets: label,
            alpha: 0,
            y: y - 30,
            duration: 300,
            onComplete: () => label.destroy(),
          });
        });
      },
    });
  }

  /** Joins arrive in bursts, so each toast is stacked below the last instead
   * of being printed on top of it. The slot frees up as the toast fades. */
  private toastSlots: boolean[] = [];

  /** A busy live joins faster than anyone can read. Past this the extra
   * arrivals are simply not announced -- the troop counter already shows them,
   * and a wall of toasts would cover the fight. */
  private static readonly MAX_TOASTS = 4;

  private takeToastSlot(): number {
    for (let i = 0; i < EffectsManager.MAX_TOASTS; i += 1) {
      if (!this.toastSlots[i]) {
        this.toastSlots[i] = true;
        return i;
      }
    }
    return -1;
  }

  joinToast(text: string, x: number, y: number) {
    const slot = this.takeToastSlot();
    if (slot === -1) return;
    const label = this.scene.add
      .text(x, y + slot * 34, text, {
        fontFamily: "Segoe UI, sans-serif",
        fontSize: "26px",
        fontStyle: "bold",
        color: "#8be28b",
        stroke: "#000",
        strokeThickness: 4,
      })
      .setOrigin(0.5)
      .setDepth(75)
      .setAlpha(0);

    this.scene.tweens.add({
      targets: label,
      alpha: 1,
      duration: 200,
      onComplete: () => {
        this.scene.time.delayedCall(1200, () => {
          this.toastSlots[slot] = false;
          this.scene.tweens.add({
            targets: label,
            alpha: 0,
            duration: 300,
            onComplete: () => label.destroy(),
          });
        });
      },
    });
  }
}
