import Phaser from "phaser";
import { ARENA_WIDTH, XP_BAR_Y } from "../constants";

interface Bar {
  bg: Phaser.GameObjects.Rectangle;
  fill: Phaser.GameObjects.Rectangle;
  label: Phaser.GameObjects.Text;
  nameLabel: Phaser.GameObjects.Text;
  danger: boolean;
  baseColor: number;
  /** "Digite A"/"Digite B": how a real viewer actually joins this side.
   * Character mode only shows an avatar for someone who typed the letter in
   * chat (or who already gifted), so without this prompt there is nothing
   * on screen telling a first-time viewer that typing does anything at all. */
  joinPrompt: Phaser.GameObjects.Text;
}

const BAR_WIDTH = ARENA_WIDTH / 2 - 40;
const BAR_HEIGHT = 34;

export class XPManager {
  private scene: Phaser.Scene;
  private barA!: Bar;
  private barB!: Bar;
  private maxA = 100000;
  private maxB = 100000;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
  }

  init(nameA: string, colorA: string, nameB: string, colorB: string, maxA: number, maxB: number) {
    this.maxA = maxA;
    this.maxB = maxB;

    this.barA = this.buildBar(20, colorA, "A");
    this.barB = this.buildBar(ARENA_WIDTH - 20 - BAR_WIDTH, colorB, "B");

    this.barA.nameLabel.setText(nameA.toUpperCase());
    this.barB.nameLabel.setText(nameB.toUpperCase());
  }

  private buildBar(x: number, color: string, keyword: "A" | "B"): Bar {
    const bg = this.scene.add.rectangle(x, XP_BAR_Y, BAR_WIDTH, BAR_HEIGHT, 0x000000, 0.55).setOrigin(0, 0.5).setDepth(90);
    bg.setStrokeStyle(2, 0xffffff, 0.4);
    const baseColor = Phaser.Display.Color.HexStringToColor(color).color;
    const fill = this.scene.add
      .rectangle(x + 2, XP_BAR_Y, BAR_WIDTH - 4, BAR_HEIGHT - 4, baseColor, 1)
      .setOrigin(0, 0.5)
      .setDepth(91);
    const nameLabel = this.scene.add
      .text(x + BAR_WIDTH / 2, XP_BAR_Y - 28, "", {
        fontFamily: "Segoe UI, sans-serif",
        fontSize: "20px",
        fontStyle: "bold",
        color: "#ffffff",
        stroke: "#000",
        strokeThickness: 4,
      })
      .setOrigin(0.5)
      .setDepth(92);
    const label = this.scene.add
      .text(x + BAR_WIDTH / 2, XP_BAR_Y, "", {
        fontFamily: "Segoe UI, sans-serif",
        fontSize: "16px",
        fontStyle: "bold",
        color: "#ffffff",
        stroke: "#000",
        strokeThickness: 3,
      })
      .setOrigin(0.5)
      .setDepth(93);

    const joinPrompt = this.scene.add
      .text(x + BAR_WIDTH / 2, XP_BAR_Y + BAR_HEIGHT / 2 + 26, `DIGITE ${keyword}`, {
        fontFamily: "Segoe UI, sans-serif",
        fontSize: "22px",
        fontStyle: "bold",
        color: "#fff23c",
        stroke: "#000",
        strokeThickness: 5,
      })
      .setOrigin(0.5)
      .setDepth(94);
    // A steady blink, not a fade to nothing: it has to keep reading as "type
    // this" to someone glancing at the stream for a second, not disappear
    // right when they look.
    this.scene.tweens.add({
      targets: joinPrompt,
      alpha: 0.25,
      duration: 550,
      yoyo: true,
      repeat: -1,
      ease: "Sine.easeInOut",
    });

    return { bg, fill, label, nameLabel, danger: false, baseColor, joinPrompt };
  }

  update(xpA: number, xpB: number) {
    this.animateBar(this.barA, xpA, this.maxA);
    this.animateBar(this.barB, xpB, this.maxB);
  }

  private animateBar(bar: Bar, xp: number, max: number) {
    const pct = Phaser.Math.Clamp(xp / max, 0, 1);
    const width = Math.max(2, (BAR_WIDTH - 4) * pct);

    this.scene.tweens.add({ targets: bar.fill, width, duration: 350, ease: "Cubic.easeOut" });
    bar.label.setText(`❤️ ${Math.max(0, Math.round(xp)).toLocaleString("pt-BR")} / ${max.toLocaleString("pt-BR")}`);

    const isDanger = pct <= 0.1;
    if (isDanger && !bar.danger) {
      bar.danger = true;
      this.scene.tweens.add({
        targets: bar.bg,
        alpha: 0.25,
        duration: 260,
        yoyo: true,
        repeat: -1,
      });
    } else if (!isDanger && bar.danger) {
      bar.danger = false;
      this.scene.tweens.killTweensOf(bar.bg);
      bar.bg.setAlpha(0.55);
    }

    bar.fill.setFillStyle(pct <= 0.25 ? 0xff4d4d : bar.baseColor);
  }
}
