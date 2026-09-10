import type { EffectsManager } from "./EffectsManager";
import { ARENA_WIDTH } from "../constants";

export class ComboManager {
  private effects: EffectsManager;

  constructor(effects: EffectsManager) {
    this.effects = effects;
  }

  /** Spec sections 17/19: shows the combo tier banner ("🔥 COMBO x100 -
   * CARLOS") whenever a streak crosses a threshold big enough to matter. */
  announce(username: string, count: number, tierLabel: string | null) {
    if (!tierLabel || count < 10) return;
    this.effects.bannerText(`🔥 COMBO x${count}`, ARENA_WIDTH / 2, 480, "#ffb84d", 44);
    this.effects.bannerText(`${tierLabel} — ${username.toUpperCase()}`, ARENA_WIDTH / 2, 540, "#ffffff", 26);
  }
}
