import Phaser from "phaser";
import type {
  ArenaMessage,
  ArmyTotals,
  CharacterPayload,
  PlayerEnlistedMessage,
  PvpPlayerPayload,
  StateSyncMessage,
  TankShotMessage,
} from "../../types/events";
import { resolveAssetUrl } from "./avatarTexture";
import { AudioManager } from "./managers/AudioManager";
import { ComboManager } from "./managers/ComboManager";
import { EffectsManager } from "./managers/EffectsManager";
import { FeedManager } from "./managers/FeedManager";
import { MissileManager } from "./managers/MissileManager";
import { PvpAvatarManager } from "./managers/PvpAvatarManager";
import { RankingManager } from "./managers/RankingManager";
import { EventSocket } from "./net/EventSocket";
import { ARENA_HEIGHT, ARENA_WIDTH, CEILING_Y, CENTER_X, FLOOR_Y, XP_BAR_Y } from "./constants";

const BAR_WIDTH = ARENA_WIDTH / 2 - 40;
const GUNNER_TARGET_HEIGHT = 560;
/** Where the cannon barrel ends, as a fraction of the sprite's size measured
 * from its centre. Mirrored automatically for the flipped side. */
const MUZZLE = { x: 0.36, y: 0.06 };

interface Gunner {
  sprite: Phaser.GameObjects.Image | Phaser.GameObjects.Text;
  meta: CharacterPayload;
  side: "A" | "B";
  baseX: number;
  baseY: number;
  facing: 1 | -1;
}

/** Tank war: the two characters are the gunners and the viewers are their
 * troops. Viewers enlist by typing a keyword in chat, a gift makes the
 * sender's tank swivel and fire, and whoever the shell lands on explodes and
 * leaves the arena. The gunners never move from their spot -- they just
 * breathe, sway, punch the air and recoil. */
export default class TankWarScene extends Phaser.Scene {
  private sessionId!: string;
  private socket!: EventSocket;

  private soldiers!: PvpAvatarManager;
  private effects!: EffectsManager;
  private missiles!: MissileManager;
  private combos!: ComboManager;
  private feed!: FeedManager;
  private audio!: AudioManager;
  private ranking: RankingManager | null = null;

  private gunners: Partial<Record<"A" | "B", Gunner>> = {};
  private teamColors: Record<"A" | "B", string> = { A: "#e01b24", B: "#2a7d2e" };
  private teamNames: Record<"A" | "B", string> = { A: "TIME A", B: "TIME B" };
  private armyLabels: Partial<Record<"A" | "B", Phaser.GameObjects.Text>> = {};
  private victoryShown = false;

  constructor() {
    super("TankWarScene");
  }

  init(data: { sessionId: string }) {
    this.sessionId = data.sessionId;
  }

  create() {
    this.matter.world.setBounds(0, CEILING_Y - 200, ARENA_WIDTH, FLOOR_Y - CEILING_Y + 460);

    this.add.rectangle(ARENA_WIDTH / 2, ARENA_HEIGHT / 2, ARENA_WIDTH, ARENA_HEIGHT, 0x11111a).setDepth(-10);

    this.matter.add.rectangle(ARENA_WIDTH / 2, FLOOR_Y + 15, ARENA_WIDTH, 30, { isStatic: true });
    this.matter.add.rectangle(-10, ARENA_HEIGHT / 2, 20, ARENA_HEIGHT, { isStatic: true });
    this.matter.add.rectangle(ARENA_WIDTH + 10, ARENA_HEIGHT / 2, 20, ARENA_HEIGHT, { isStatic: true });
    this.matter.add.rectangle(CENTER_X, (CEILING_Y + FLOOR_Y) / 2, 10, FLOOR_Y - CEILING_Y, { isStatic: true });

    const divider = this.add.graphics().setDepth(5);
    divider.lineStyle(4, 0xffffff, 0.25);
    for (let y = CEILING_Y; y < FLOOR_Y; y += 30) divider.lineBetween(CENTER_X, y, CENTER_X, y + 16);

    this.soldiers = new PvpAvatarManager(this, { scaleWithPower: false, showPowerLabel: false });
    this.effects = new EffectsManager(this);
    this.missiles = new MissileManager(this, this.effects);
    this.combos = new ComboManager(this.effects);
    this.feed = new FeedManager(this);
    this.audio = new AudioManager();
    this.audio.init();

    this.buildArmyLabels();

    this.socket = new EventSocket(this.sessionId, (msg) => this.handleMessage(msg));
    this.socket.connect();

    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.socket?.close());
  }

  update() {
    this.soldiers.syncOverlays();
  }

  private buildArmyLabels() {
    (["A", "B"] as const).forEach((side) => {
      const x = side === "A" ? 20 + BAR_WIDTH / 2 : ARENA_WIDTH - 20 - BAR_WIDTH / 2;
      this.add
        .text(x, XP_BAR_Y - 26, "", {
          fontFamily: "Segoe UI, sans-serif",
          fontSize: "22px",
          fontStyle: "bold",
          color: "#ffffff",
          stroke: "#000",
          strokeThickness: 5,
        })
        .setOrigin(0.5)
        .setDepth(92)
        .setName(`army_name_${side}`);

      this.armyLabels[side] = this.add
        .text(x, XP_BAR_Y + 6, "", {
          fontFamily: "Segoe UI, sans-serif",
          fontSize: "20px",
          fontStyle: "bold",
          color: "#ffffff",
          stroke: "#000",
          strokeThickness: 4,
        })
        .setOrigin(0.5)
        .setDepth(92);
    });
  }

  private handleMessage(msg: ArenaMessage) {
    switch (msg.type) {
      case "state_sync":
        this.applyStateSync(msg as StateSyncMessage);
        break;
      case "player_enlisted":
        this.handleEnlist(msg as PlayerEnlistedMessage);
        break;
      case "tank_shot":
        this.handleTankShot(msg as TankShotMessage);
        break;
      case "battle_restarted":
        this.victoryShown = false;
        break;
    }
  }

  private applyStateSync(msg: StateSyncMessage) {
    this.teamColors = { A: msg.side_a.team_color, B: msg.side_b.team_color };
    this.teamNames = { A: msg.side_a.name.toUpperCase(), B: msg.side_b.name.toUpperCase() };

    (["A", "B"] as const).forEach((side) => {
      const label = this.children.getByName(`army_name_${side}`) as Phaser.GameObjects.Text | null;
      label?.setText(this.teamNames[side]);
      label?.setColor(this.teamColors[side]);
    });

    const bgUrl = resolveAssetUrl(msg.battle.background_url);
    if (bgUrl && !this.textures.exists("tank_bg")) {
      this.load.setCORS("anonymous");
      this.load.image("tank_bg", bgUrl);
      this.load.once("filecomplete-image-tank_bg", () => {
        this.add
          .image(ARENA_WIDTH / 2, ARENA_HEIGHT / 2, "tank_bg")
          .setDisplaySize(ARENA_WIDTH, ARENA_HEIGHT)
          .setDepth(-9);
      });
      this.load.start();
    }

    if (!this.gunners.A) this.spawnGunner("A", msg.side_a);
    if (!this.gunners.B) this.spawnGunner("B", msg.side_b);

    if (!this.ranking) this.ranking = new RankingManager(this, msg.session_id);

    for (const player of msg.players) {
      if (player.eliminated) continue;
      this.soldiers.spawnOrGet(player, this.teamColors[player.team], false);
    }
    this.updateArmies({
      A: { alive: msg.teams?.A.alive ?? 0, recruited: msg.teams?.A.fighters ?? 0 },
      B: { alive: msg.teams?.B.alive ?? 0, recruited: msg.teams?.B.fighters ?? 0 },
    });
  }

  private spawnGunner(side: "A" | "B", meta: CharacterPayload) {
    const x = meta.pos_x * ARENA_WIDTH;
    const y = meta.pos_y * ARENA_HEIGHT;
    const facing: 1 | -1 = meta.flip_h ? -1 : 1;
    const url = resolveAssetUrl(meta.image_url);

    if (meta.shadow) {
      this.add
        .ellipse(x, y + GUNNER_TARGET_HEIGHT * meta.scale * 0.46, 300 * meta.scale, 46 * meta.scale, 0x000000, 0.35)
        .setDepth(9);
    }

    const register = (sprite: Phaser.GameObjects.Image | Phaser.GameObjects.Text) => {
      const gunner: Gunner = { sprite, meta, side, baseX: x, baseY: y, facing };
      this.gunners[side] = gunner;
      this.startIdle(gunner);
    };

    if (url) {
      const key = `gunner_${meta.id}`;
      if (this.textures.exists(key)) {
        register(this.buildGunnerSprite(key, x, y, meta));
      } else {
        const placeholder = this.add.text(x, y, "🪖", { fontSize: "120px" }).setOrigin(0.5).setDepth(10);
        register(placeholder);
        this.load.setCORS("anonymous");
        this.load.image(key, url);
        this.load.once(`filecomplete-image-${key}`, () => {
          placeholder.destroy();
          register(this.buildGunnerSprite(key, x, y, meta));
        });
        this.load.start();
      }
    } else {
      // No art uploaded yet -- keep the mode playable with a placeholder.
      const placeholder = this.add
        .text(x, y, "🪖", { fontSize: `${140 * meta.scale}px` })
        .setOrigin(0.5)
        .setDepth(10);
      register(placeholder);
    }
  }

  private buildGunnerSprite(key: string, x: number, y: number, meta: CharacterPayload): Phaser.GameObjects.Image {
    const img = this.add.image(x, y, key).setDepth(10);
    img.setScale((GUNNER_TARGET_HEIGHT * meta.scale) / img.height);
    if (meta.flip_h) img.setFlipX(true);
    if (meta.glow) {
      try {
        (img as any).preFX?.addGlow(Phaser.Display.Color.HexStringToColor(meta.team_color).color, 3, 0, false, 0.1, 14);
      } catch {
        /* glow needs WebGL */
      }
    }
    return img;
  }

  /** The gunners hold their ground but stay alive: a slow breath, a lazy
   * sway, and every few seconds a fist pump. */
  private startIdle(gunner: Gunner) {
    const { sprite } = gunner;
    const baseScale = (sprite as any).scale ?? 1;

    this.tweens.add({
      targets: sprite,
      y: gunner.baseY - 10,
      duration: 1800,
      yoyo: true,
      repeat: -1,
      ease: "Sine.easeInOut",
    });
    this.tweens.add({
      targets: sprite,
      rotation: 0.02 * gunner.facing,
      duration: 2600,
      yoyo: true,
      repeat: -1,
      ease: "Sine.easeInOut",
    });

    this.time.addEvent({
      delay: Phaser.Math.Between(4000, 7000),
      loop: true,
      callback: () => {
        if (!sprite.active) return;
        this.tweens.add({
          targets: sprite,
          scale: baseScale * 1.05,
          duration: 140,
          yoyo: true,
          repeat: 1,
          ease: "Quad.easeOut",
        });
      },
    });
  }

  private muzzleOf(gunner: Gunner): { x: number; y: number } {
    const sprite = gunner.sprite as Phaser.GameObjects.Image;
    const width = (sprite as any).displayWidth ?? 200;
    const height = (sprite as any).displayHeight ?? 200;
    return {
      x: sprite.x + width * MUZZLE.x * gunner.facing,
      y: sprite.y + height * MUZZLE.y,
    };
  }

  /** Swivels the tank toward its target, kicks back from the recoil, then
   * settles back to the idle pose. */
  private aimAndRecoil(gunner: Gunner, targetY: number) {
    const sprite = gunner.sprite;
    const tilt = Phaser.Math.Clamp((targetY - sprite.y) / 2600, -0.12, 0.12) * gunner.facing;

    this.tweens.killTweensOf(sprite);
    this.tweens.add({
      targets: sprite,
      rotation: tilt,
      x: gunner.baseX - 16 * gunner.facing,
      duration: 110,
      yoyo: true,
      ease: "Quad.easeOut",
      onComplete: () => {
        sprite.setPosition(gunner.baseX, gunner.baseY);
        sprite.rotation = 0;
        this.startIdle(gunner);
      },
    });
  }

  private handleEnlist(msg: PlayerEnlistedMessage) {
    const player = msg.player as PvpPlayerPayload;
    this.soldiers.spawnOrGet(player, this.teamColors[player.team], true).then(() => {
      const name = (player.nickname || player.username).toUpperCase();
      this.effects.joinToast(`${name} ENTROU NO ${this.teamNames[player.team]}`, ARENA_WIDTH / 2, 700);
    });
  }

  private async handleTankShot(msg: TankShotMessage) {
    const gunner = this.gunners[msg.shooter_side];
    const shooterName = (msg.player.nickname || msg.player.username).toUpperCase();

    // The sender fights on the side they enlisted for, so make sure their own
    // soldier is on the field too.
    this.soldiers.spawnOrGet(msg.player, this.teamColors[msg.player.team], true);

    const targets = msg.hits
      .map((hit) => ({ hit, fighter: this.soldiers.get(hit.user_id) }))
      .filter((t) => t.fighter);

    const firstTarget = targets[0]?.fighter;
    if (gunner) {
      this.aimAndRecoil(gunner, firstTarget ? firstTarget.sprite.y : gunner.baseY);
    }

    const heavy = msg.gift.coins >= 100 || msg.kills > 1;
    const muzzle = gunner ? this.muzzleOf(gunner) : { x: CENTER_X, y: CEILING_Y };

    targets.forEach(({ hit, fighter }, index) => {
      this.time.delayedCall(index * 120, () => {
        if (!fighter) return;
        this.missiles.fireShell(muzzle.x, muzzle.y, fighter.sprite.x, fighter.sprite.y, heavy, () => {
          this.soldiers.setPower(hit.user_id, hit.power);
          if (hit.eliminated) {
            this.effects.burst(fighter.sprite.x, fighter.sprite.y, 0xff5533, 24, 260);
            this.soldiers.eliminate(hit.user_id);
          } else {
            this.effects.floatingNumber(
              fighter.sprite.x,
              fighter.sprite.y - 30,
              `-${Math.round(hit.damage)}`,
              "#ff5b5b"
            );
          }
        });
      });
    });

    this.audio.missile();
    // One shake for the whole volley -- shaking per shell stacks into a mess.
    this.effects.shake(msg.kills > 1 ? 0.012 : 0.006, 180);

    if (msg.kills > 0) {
      this.effects.bannerText(
        `${shooterName} ELIMINOU ${msg.kills}`,
        msg.shooter_side === "A" ? ARENA_WIDTH * 0.3 : ARENA_WIDTH * 0.7,
        520,
        "#ffd700",
        34
      );
    }

    if (msg.combo.count >= 10) {
      this.combos.announce(shooterName, msg.combo.count, msg.combo.tier_label);
      this.audio.combo();
    }

    this.feed.push(
      `${msg.gift.icon} ${shooterName} ${msg.gift.coins}💰 x${msg.quantity}` +
        (msg.kills ? ` — ${msg.kills} 💀` : "")
    );

    this.updateArmies(msg.armies);
    if (msg.winner_side) {
      // The server declares the winner the instant the shot resolves, but the
      // shells are still in the air -- let them land before celebrating.
      const flightMs = 500 + targets.length * 120;
      this.time.delayedCall(flightMs, () => this.showVictory(msg.winner_side as string));
    }
  }

  private updateArmies(armies: ArmyTotals) {
    (["A", "B"] as const).forEach((side) => {
      this.armyLabels[side]?.setText(`🪖 ${armies[side].alive} / ${armies[side].recruited}`);
    });
  }

  private showVictory(side: string) {
    if (this.victoryShown) return;
    this.victoryShown = true;
    this.audio.victoryFanfare();
    this.effects.bannerText("🏆 VITÓRIA!", ARENA_WIDTH / 2, ARENA_HEIGHT / 2 - 60, "#ffd700", 64);
    this.effects.bannerText(this.teamNames[side as "A" | "B"], ARENA_WIDTH / 2, ARENA_HEIGHT / 2 + 10, "#ffffff", 40);

    const gunner = this.gunners[side as "A" | "B"];
    if (gunner) {
      this.tweens.add({
        targets: gunner.sprite,
        y: gunner.baseY - 40,
        duration: 300,
        yoyo: true,
        repeat: 4,
        ease: "Sine.easeOut",
      });
    }
  }
}
