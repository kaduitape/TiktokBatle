import Phaser from "phaser";
import { API_BASE } from "../../api/client";
import type { AttackMessage, ArenaMessage, CharacterPayload, PlayerJoinedMessage, StateSyncMessage } from "../../types/events";
import { buildCharacterObject, isAnimated } from "./characterSprite";
import { AudioManager } from "./managers/AudioManager";
import { AvatarManager } from "./managers/AvatarManager";
import { ComboManager } from "./managers/ComboManager";
import { EffectsManager } from "./managers/EffectsManager";
import { FeedManager } from "./managers/FeedManager";
import { HealManager } from "./managers/HealManager";
import { MissileManager } from "./managers/MissileManager";
import { ProjectileManager } from "./managers/ProjectileManager";
import { RankingManager } from "./managers/RankingManager";
import { XPManager } from "./managers/XPManager";
import { EventSocket } from "./net/EventSocket";
import { ARENA_HEIGHT, ARENA_WIDTH, CEILING_Y, CENTER_X, FLOOR_Y } from "./constants";

function resolveUrl(url: string | null): string | null {
  if (!url) return null;
  if (url.startsWith("http") || url.startsWith("data:")) return url;
  return `${API_BASE}${url}`;
}

export default class GameScene extends Phaser.Scene {
  private sessionId!: string;
  private socket!: EventSocket;

  private avatarManager!: AvatarManager;
  private effects!: EffectsManager;
  private projectiles!: ProjectileManager;
  private missiles!: MissileManager;
  private heals!: HealManager;
  private combos!: ComboManager;
  private xp!: XPManager;
  private ranking: RankingManager | null = null;
  private feed!: FeedManager;
  private audio!: AudioManager;

  private charSpriteA!: Phaser.GameObjects.Image | Phaser.GameObjects.Text;
  private charSpriteB!: Phaser.GameObjects.Image | Phaser.GameObjects.Text;
  private sideAMeta!: CharacterPayload;
  private sideBMeta!: CharacterPayload;

  constructor() {
    super("GameScene");
  }

  init(data: { sessionId: string }) {
    this.sessionId = data.sessionId;
  }

  create() {
    this.matter.world.setBounds(0, CEILING_Y - 200, ARENA_WIDTH, FLOOR_Y - CEILING_Y + 260 + 200);

    this.add.rectangle(ARENA_WIDTH / 2, ARENA_HEIGHT / 2, ARENA_WIDTH, ARENA_HEIGHT, 0x11111a).setDepth(-10);

    // floor
    this.matter.add.rectangle(ARENA_WIDTH / 2, FLOOR_Y + 15, ARENA_WIDTH, 30, { isStatic: true });
    // walls
    this.matter.add.rectangle(-10, ARENA_HEIGHT / 2, 20, ARENA_HEIGHT, { isStatic: true });
    this.matter.add.rectangle(ARENA_WIDTH + 10, ARENA_HEIGHT / 2, 20, ARENA_HEIGHT, { isStatic: true });
    // center divider so the two piles of avatars stay visually separated
    this.matter.add.rectangle(CENTER_X, (CEILING_Y + FLOOR_Y) / 2, 10, FLOOR_Y - CEILING_Y, { isStatic: true });

    const divider = this.add.graphics().setDepth(5);
    divider.lineStyle(4, 0xffffff, 0.25);
    for (let y = CEILING_Y; y < FLOOR_Y; y += 30) {
      divider.lineBetween(CENTER_X, y, CENTER_X, y + 16);
    }

    this.add.text(24, 40, "A", { fontFamily: "Segoe UI", fontSize: "34px", fontStyle: "bold", color: "#ffd700" }).setDepth(90);
    this.add
      .text(ARENA_WIDTH - 24, 40, "B", { fontFamily: "Segoe UI", fontSize: "34px", fontStyle: "bold", color: "#ffd700" })
      .setOrigin(1, 0)
      .setDepth(90);

    this.avatarManager = new AvatarManager(this);
    this.effects = new EffectsManager(this);
    this.projectiles = new ProjectileManager(this, this.effects);
    this.missiles = new MissileManager(this, this.effects);
    this.heals = new HealManager(this, this.effects);
    this.combos = new ComboManager(this.effects);
    this.xp = new XPManager(this);
    this.feed = new FeedManager(this);
    this.audio = new AudioManager();
    this.audio.init();

    this.socket = new EventSocket(this.sessionId, (msg) => this.handleMessage(msg));
    this.socket.connect();

    const closeSocket = () => this.socket?.close();
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, closeSocket);
    // game.destroy() tears the scene down without a SHUTDOWN, so without this
    // the socket would outlive the scene and crash on the next message.
    this.events.once(Phaser.Scenes.Events.DESTROY, closeSocket);
  }

  private handleMessage(msg: ArenaMessage) {
    switch (msg.type) {
      case "state_sync":
        this.applyStateSync(msg as StateSyncMessage);
        break;
      case "player_joined":
        this.handleJoin(msg as PlayerJoinedMessage);
        break;
      case "attack":
      case "heal":
        this.handleAttack(msg as AttackMessage);
        break;
      case "sudden_death":
        this.effects.bannerText("🔥 MORTE SÚBITA 🔥", ARENA_WIDTH / 2, ARENA_HEIGHT / 2 - 200, "#ff3333", 56);
        break;
      case "new_round_countdown":
        this.showCountdown(msg.seconds);
        break;
      case "battle_restarted":
        this.victoryShown = false;
        this.xp.update(msg.xp.a, msg.xp.b);
        this.audio.updateDanger(1, 1, false);
        break;
    }
  }

  private countdownLabel: Phaser.GameObjects.Text | null = null;
  private showCountdown(seconds: number) {
    if (!this.countdownLabel) {
      this.countdownLabel = this.add
        .text(ARENA_WIDTH / 2, ARENA_HEIGHT / 2, "", {
          fontFamily: "Segoe UI, sans-serif",
          fontSize: "90px",
          fontStyle: "bold",
          color: "#ffffff",
          stroke: "#000",
          strokeThickness: 8,
        })
        .setOrigin(0.5)
        .setDepth(99);
    }
    this.countdownLabel.setText(seconds > 0 ? `NOVA BATALHA EM: ${seconds}` : "");
    if (seconds <= 1) {
      this.time.delayedCall(900, () => {
        this.countdownLabel?.destroy();
        this.countdownLabel = null;
      });
    }
  }

  private characterPosition(meta: CharacterPayload, side: "A" | "B"): { x: number; y: number } {
    // A newly registered character used to default to the exact centre of the
    // arena. When both sides had that untouched value, the final sprite drawn
    // covered the first one and made it look as if both sides had one image.
    // Preserve positions chosen in the editor, but split untouched defaults.
    const usesUntouchedDefault = meta.pos_x === 0.5 && meta.pos_y === 0.5;
    return {
      x: (usesUntouchedDefault ? (side === "A" ? 0.25 : 0.75) : meta.pos_x) * ARENA_WIDTH,
      y: meta.pos_y * ARENA_HEIGHT,
    };
  }

  private renderCharacter(meta: CharacterPayload, side: "A" | "B"): Phaser.GameObjects.Image | Phaser.GameObjects.Text {
    const { x, y } = this.characterPosition(meta, side);
    const url = resolveUrl(meta.image_url);

    if (meta.shadow) {
      this.add.ellipse(x, y + 260 * meta.scale, 260 * meta.scale, 50 * meta.scale, 0x000000, 0.35).setDepth(9);
    }

    let obj: Phaser.GameObjects.Image | Phaser.GameObjects.Text;
    if (url) {
      const key = `char_${meta.id}`;
      if (this.textures.exists(key)) {
        obj = this.buildCharSprite(key, x, y, meta);
      } else {
        this.load.setCORS("anonymous");
        this.load.image(key, url);
        obj = this.add.text(x, y, "…", { fontSize: "40px" }).setOrigin(0.5).setDepth(10);
        this.load.once(`filecomplete-image-${key}`, () => {
          obj.destroy();
          const sprite = this.buildCharSprite(key, x, y, meta);
          if (meta.id === this.sideAMeta?.id) this.charSpriteA = sprite;
          if (meta.id === this.sideBMeta?.id) this.charSpriteB = sprite;
        });
        this.load.start();
      }
    } else {
      obj = this.add
        .text(x, y, "🧍", { fontSize: `${140 * meta.scale}px`, color: meta.team_color })
        .setOrigin(0.5)
        .setDepth(10);
      if (meta.flip_h) obj.setFlipX(true);
    }

    return obj;
  }

  private buildCharSprite(key: string, x: number, y: number, meta: CharacterPayload): Phaser.GameObjects.Image {
    const img = buildCharacterObject(this, key, x, y, meta).setDepth(10);
    const targetHeight = 900 * meta.scale;
    const scale = targetHeight / img.height;
    img.setScale(scale);
    if (meta.flip_h) img.setFlipX(true);
    if (meta.outline) img.setTint(0xffffff);
    if (meta.glow) {
      try {
        (img as any).preFX?.addGlow(Phaser.Display.Color.HexStringToColor(meta.team_color).color, 3, 0, false, 0.1, 16);
      } catch {
        /* glow requires WebGL; ignore on canvas renderer */
      }
    }
    // A sheet already carries its own motion; the float would fight it.
    if (!isAnimated(meta)) {
      this.tweens.add({ targets: img, y: y - 8, duration: 1400, yoyo: true, repeat: -1, ease: "Sine.easeInOut" });
    }
    return img;
  }

  private applyStateSync(msg: StateSyncMessage) {
    this.sideAMeta = msg.side_a;
    this.sideBMeta = msg.side_b;

    if (msg.battle.background_url) {
      const bgUrl = resolveUrl(msg.battle.background_url);
      if (bgUrl) {
        this.load.setCORS("anonymous");
        this.load.image("battle_bg", bgUrl);
        this.load.once("filecomplete-image-battle_bg", () => {
          this.add.image(ARENA_WIDTH / 2, ARENA_HEIGHT / 2, "battle_bg").setDisplaySize(ARENA_WIDTH, ARENA_HEIGHT).setDepth(-9);
        });
        this.load.start();
      }
    }

    this.charSpriteA = this.renderCharacter(msg.side_a, "A");
    this.charSpriteB = this.renderCharacter(msg.side_b, "B");

    this.xp.init(msg.side_a.name, msg.side_a.team_color, msg.side_b.name, msg.side_b.team_color, msg.side_a.xp_max, msg.side_b.xp_max);
    this.xp.update(msg.xp.a, msg.xp.b);
    this.audio.updateDanger(msg.xp.a / msg.side_a.xp_max, msg.xp.b / msg.side_b.xp_max, !!msg.winner_side);

    this.ranking = new RankingManager(this, msg.session_id);

    for (const player of msg.players) {
      const teamColor = player.team === "A" ? msg.side_a.team_color : msg.side_b.team_color;
      this.avatarManager.spawnOrGet(player, teamColor, false);
    }
  }

  private handleJoin(msg: PlayerJoinedMessage) {
    if (!this.sideAMeta) return;
    const teamColor = msg.player.team === "A" ? this.sideAMeta.team_color : this.sideBMeta.team_color;
    this.avatarManager.spawnOrGet(msg.player, teamColor, true).then(() => {
      const name = (msg.player.nickname || msg.player.username).toUpperCase();
      this.effects.joinToast(`${name} ENTROU NA BATALHA`, ARENA_WIDTH / 2, 700);
    });
  }

  private targetPositionFor(side: "A" | "B"): { x: number; y: number } {
    const sprite = side === "A" ? this.charSpriteA : this.charSpriteB;
    if (sprite) return { x: sprite.x, y: sprite.y };
    const meta = side === "A" ? this.sideAMeta : this.sideBMeta;
    return this.characterPosition(meta, side);
  }

  private async handleAttack(msg: AttackMessage) {
    if (!this.sideAMeta || !this.sideBMeta) return;

    const teamColor = msg.player.team === "A" ? this.sideAMeta.team_color : this.sideBMeta.team_color;
    const entry = await this.avatarManager.spawnOrGet(msg.player, teamColor, true);
    this.avatarManager.highlight(msg.player.user_id);

    const from = { x: entry.body.x, y: entry.body.y };
    const target = this.targetPositionFor(msg.target_side);
    const displayName = (msg.player.nickname || msg.player.username).toUpperCase();
    const isHeal = msg.type === "heal";
    const color = isHeal ? "#66ffb2" : "#ff5b5b";
    const sign = isHeal ? "+" : "";

    const showNumber = () =>
      this.effects.floatingNumber(target.x, target.y - 40, `${sign}${Math.round(msg.xp_delta)}`, color);

    const tier = msg.combo.tier_animation;
    const showNumberIfAny = () => {
      if (msg.xp_delta !== 0) showNumber();
    };

    if (msg.gift.action_type === "special" && msg.gift.animation_key === "meteor") {
      this.effects.bannerText(`☄️ ${displayName} ATIVOU METEORO!`, target.x, target.y - 320, "#ff9955", 34);
      this.missiles.meteor(target.x, target.y, showNumberIfAny);
    } else if (msg.gift.action_type === "special" && msg.gift.animation_key === "lightning") {
      this.missiles.lightning(target.x, target.y, showNumberIfAny);
    } else if (msg.gift.action_type === "special" && msg.gift.animation_key === "airstrike") {
      this.missiles.airstrike(target.y - 320, target.x, showNumberIfAny);
    } else if (msg.gift.action_type === "special" && msg.gift.animation_key === "hurricane") {
      this.effects.bannerText(`🌪️ FURACÃO — ${displayName}`, target.x, 480, "#8fd9ff", 38);
      this.avatarManager.spinAll(0.28);
      this.time.delayedCall(3000, () => this.avatarManager.spinAll(0));
    } else if (msg.gift.action_type === "special" && msg.gift.animation_key === "shockwave") {
      this.effects.bannerText(`💥 ONDA DE CHOQUE`, target.x, 480, "#ffcc66", 38);
      this.effects.flash(target.x, target.y, 140, 0xffffff, 0.7);
      this.effects.shake(0.02, 250);
      this.avatarManager.applyRadialForce(target.x, target.y, 0.07, 520);
    } else if (msg.gift.action_type === "special" && msg.gift.animation_key === "giant") {
      this.effects.bannerText(`${displayName} FICOU GIGANTE!`, target.x, 480, "#ffd700", 34);
      this.avatarManager.makeGiant(msg.player.user_id);
    } else if (isHeal) {
      const big = msg.gift.action_type === "super_heal" || tier === "special" || tier === "bazooka";
      this.heals.fireHeal(from.x, from.y, target.x, target.y, big, showNumber);
    } else if (msg.gift.action_type === "missile" || tier === "bazooka" || tier === "special") {
      this.missiles.fireMissile(from.x, from.y, target.x, target.y, tier === "special", showNumber);
    } else if (tier === "burst" || tier === "minigun") {
      this.projectiles.fireBurst(from.x, from.y, target.x, target.y, msg.combo.count, () => {});
      this.time.delayedCall(300, showNumber);
    } else {
      this.projectiles.fireShot(from.x, from.y, target.x, target.y, showNumber);
    }

    this.playSfxFor(msg);

    if (msg.combo.count >= 10) {
      this.combos.announce(displayName, msg.combo.count, msg.combo.tier_label);
      this.audio.combo();
    }

    const deltaText = msg.xp_delta !== 0 ? ` ${sign}${Math.round(msg.xp_delta)}` : "";
    this.feed.push(`${msg.gift.icon} ${displayName} x${msg.quantity}${deltaText}`);

    this.xp.update(msg.xp.a, msg.xp.b);
    this.audio.updateDanger(msg.xp.a / msg.xp_max.a, msg.xp.b / msg.xp_max.b, !!msg.winner_side);

    if (msg.winner_side) {
      this.showVictory(msg.winner_side);
    }
  }

  private playSfxFor(msg: AttackMessage) {
    if (msg.type === "heal") {
      this.audio.heal();
    } else if (msg.gift.action_type === "missile" || msg.gift.action_type === "special") {
      this.audio.missile();
    } else {
      this.audio.shot();
    }
  }

  private victoryShown = false;
  private showVictory(side: string) {
    if (this.victoryShown) return;
    this.victoryShown = true;
    this.audio.victoryFanfare();
    const meta = side === "A" ? this.sideAMeta : this.sideBMeta;
    this.effects.bannerText("🏆 VITÓRIA!", ARENA_WIDTH / 2, ARENA_HEIGHT / 2 - 60, "#ffd700", 64);
    this.effects.bannerText(meta.name.toUpperCase(), ARENA_WIDTH / 2, ARENA_HEIGHT / 2 + 10, "#ffffff", 40);

    for (const entry of this.avatarManager.all()) {
      if (entry.player.team === side) {
        this.tweens.add({
          targets: entry.body,
          y: entry.body.y - 60,
          duration: 300,
          yoyo: true,
          repeat: 3,
          ease: "Sine.easeOut",
        });
      }
    }
  }
}
