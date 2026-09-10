import Phaser from "phaser";
import { API_BASE } from "../../../api/client";
import { ARENA_WIDTH, RANKING_Y } from "../constants";

interface RankingEntry {
  username: string;
  nickname: string | null;
  score: number;
}

const PANEL_WIDTH = 420;

export class RankingManager {
  private scene: Phaser.Scene;
  private sessionId: string;
  private container: Phaser.GameObjects.Container;
  private visible = false;

  constructor(scene: Phaser.Scene, sessionId: string) {
    this.scene = scene;
    this.sessionId = sessionId;
    this.container = scene.add.container(ARENA_WIDTH / 2, -300).setDepth(95);
    this.startCycle();
  }

  private startCycle() {
    this.showPanel();
    this.scene.time.addEvent({ delay: 25000, loop: true, callback: () => this.showPanel() });
  }

  private async showPanel() {
    if (this.visible) return;
    try {
      const res = await fetch(`${API_BASE}/api/sessions/${this.sessionId}/ranking?limit=3`);
      if (!res.ok) return;
      const entries: RankingEntry[] = await res.json();
      if (!entries.length) return;
      this.render(entries);
    } catch {
      // ranking is decorative; ignore fetch failures silently
    }
  }

  private render(entries: RankingEntry[]) {
    this.visible = true;
    this.container.removeAll(true);

    const bg = this.scene.add.rectangle(0, 0, PANEL_WIDTH, 46 + entries.length * 34, 0x000000, 0.65);
    bg.setStrokeStyle(2, 0xffd700, 0.8);
    this.container.add(bg);

    const title = this.scene.add
      .text(0, -bg.height / 2 + 22, "🏆 TOP GUERREIROS", {
        fontFamily: "Segoe UI, sans-serif",
        fontSize: "20px",
        fontStyle: "bold",
        color: "#ffd700",
      })
      .setOrigin(0.5);
    this.container.add(title);

    entries.forEach((e, i) => {
      const line = this.scene.add
        .text(
          0,
          -bg.height / 2 + 50 + i * 30,
          `${i + 1}  ${(e.nickname || e.username).toUpperCase()} — ${Math.round(e.score).toLocaleString("pt-BR")}`,
          { fontFamily: "Segoe UI, sans-serif", fontSize: "17px", color: "#ffffff" }
        )
        .setOrigin(0.5);
      this.container.add(line);
    });

    this.container.setPosition(ARENA_WIDTH / 2, -bg.height);
    this.scene.tweens.add({
      targets: this.container,
      y: RANKING_Y,
      duration: 500,
      ease: "Back.easeOut",
      onComplete: () => {
        this.scene.time.delayedCall(4000, () => {
          this.scene.tweens.add({
            targets: this.container,
            y: -bg.height,
            duration: 400,
            ease: "Cubic.easeIn",
            onComplete: () => {
              this.visible = false;
            },
          });
        });
      },
    });
  }
}
