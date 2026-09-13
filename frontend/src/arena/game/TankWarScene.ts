import Phaser from "phaser";
import type {
  ArenaMessage,
  ArmyTotals,
  BossBombMessage,
  CharacterPayload,
  PlayerEnlistedMessage,
  PvpPlayerPayload,
  StateSyncMessage,
  TankShotMessage,
} from "../../types/events";
import { resolveAssetUrl } from "./avatarTexture";
import {
  buildCharacterObject,
  flashAction,
  isAnimated,
  preloadActionArt,
  rememberIdlePose,
  setBackground,
  textureKeyFor,
} from "./characterSprite";
import { AudioManager } from "./managers/AudioManager";
import { ComboManager } from "./managers/ComboManager";
import { EffectsManager } from "./managers/EffectsManager";
import { FeedManager } from "./managers/FeedManager";
import { MissileManager } from "./managers/MissileManager";
import { PvpAvatarManager } from "./managers/PvpAvatarManager";
import { RankingManager } from "./managers/RankingManager";
import { XPManager } from "./managers/XPManager";
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

/** Tank war: two bosses with a huge health pool versus the viewers' armies.
 * Viewers enlist by typing a keyword in chat and every gift makes their own
 * tank swivel and shell the ENEMY BOSS -- nobody ever shoots a fellow viewer.
 * The bosses answer on their own schedule by lobbing a bomb at one active
 * enemy viewer, which takes a full-health soldier out. The bosses never move
 * from their spot: they breathe, sway, punch the air and recoil. */
export default class TankWarScene extends Phaser.Scene {
  private sessionId!: string;
  private socket!: EventSocket;

  private soldiers!: PvpAvatarManager;
  private effects!: EffectsManager;
  private missiles!: MissileManager;
  private combos!: ComboManager;
  private feed!: FeedManager;
  private audio!: AudioManager;
  private bossBars!: XPManager;
  private ranking: RankingManager | null = null;

  private background: Phaser.GameObjects.Image | null = null;
  private gunners: Partial<Record<"A" | "B", Gunner>> = {};
  /** Everything drawn for each boss, so new artwork replaces it instead of
   * being stacked behind the old drawing. */
  private gunnerParts: Partial<Record<"A" | "B", Phaser.GameObjects.GameObject[]>> = {};
  /** What each boss is currently drawn from, to skip a pointless rebuild. */
  private gunnerArt: Partial<Record<"A" | "B", string>> = {};
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
    this.bossBars = new XPManager(this);

    this.buildArmyLabels();

    this.socket = new EventSocket(this.sessionId, (msg) => this.handleMessage(msg));
    this.socket.connect();

    const closeSocket = () => this.socket?.close();
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, closeSocket);
    // game.destroy() tears the scene down without a SHUTDOWN, so without this
    // the socket would outlive the scene and crash on the next message.
    this.events.once(Phaser.Scenes.Events.DESTROY, closeSocket);
  }

  update() {
    this.soldiers.syncOverlays();
  }

  /** The boss health bars come from the shared XPManager; this is just the
   * troop count line underneath each of them. */
  private buildArmyLabels() {
    (["A", "B"] as const).forEach((side) => {
      const x = side === "A" ? 20 + BAR_WIDTH / 2 : ARENA_WIDTH - 20 - BAR_WIDTH / 2;
      this.armyLabels[side] = this.add
        .text(x, XP_BAR_Y + 32, "", {
          fontFamily: "Segoe UI, sans-serif",
          fontSize: "19px",
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
      case "boss_bomb":
        this.handleBossBomb(msg as BossBombMessage);
        break;
      case "battle_restarted":
        this.victoryShown = false;
        break;
    }
  }

  private applyStateSync(msg: StateSyncMessage) {
    this.teamColors = { A: msg.side_a.team_color, B: msg.side_b.team_color };
    this.teamNames = { A: msg.side_a.name.toUpperCase(), B: msg.side_b.name.toUpperCase() };

    this.bossBars.init(
      msg.side_a.name,
      msg.side_a.team_color,
      msg.side_b.name,
      msg.side_b.team_color,
      msg.side_a.xp_max,
      msg.side_b.xp_max
    );
    this.bossBars.update(msg.xp.a, msg.xp.b);

    this.background = setBackground(
      this,
      resolveAssetUrl(msg.battle.background_url),
      ARENA_WIDTH,
      ARENA_HEIGHT,
      this.background
    );

    // A restart republishes the whole state, which is how artwork swapped in
    // the panel reaches an arena that is already open.
    (["A", "B"] as const).forEach((side) => {
      const meta = side === "A" ? msg.side_a : msg.side_b;
      const signature = [meta.image_url, meta.sprite_columns, meta.sprite_rows, meta.sprite_frame_count, meta.sprite_fps, meta.scale, meta.pos_x, meta.pos_y, meta.flip_h].join("|");
      if (this.gunners[side] && this.gunnerArt[side] === signature) return;
      this.clearGunner(side);
      this.gunnerArt[side] = signature;
      this.spawnGunner(side, meta);
    });

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

  private clearGunner(side: "A" | "B") {
    (this.gunnerParts[side] || []).forEach((obj) => {
      this.tweens.killTweensOf(obj);
      obj.destroy();
    });
    this.gunnerParts[side] = [];
    delete this.gunners[side];
  }

  private spawnGunner(side: "A" | "B", meta: CharacterPayload) {
    const x = meta.pos_x * ARENA_WIDTH;
    const y = meta.pos_y * ARENA_HEIGHT;
    preloadActionArt(this, meta, resolveAssetUrl);
    const facing: 1 | -1 = meta.flip_h ? -1 : 1;
    const url = resolveAssetUrl(meta.image_url);

    const parts = (this.gunnerParts[side] = this.gunnerParts[side] || []);
    if (meta.shadow) {
      parts.push(
        this.add
          .ellipse(x, y + GUNNER_TARGET_HEIGHT * meta.scale * 0.46, 300 * meta.scale, 46 * meta.scale, 0x000000, 0.35)
          .setDepth(9)
      );
    }

    const register = (sprite: Phaser.GameObjects.Image | Phaser.GameObjects.Text) => {
      const gunner: Gunner = { sprite, meta, side, baseX: x, baseY: y, facing };
      this.gunners[side] = gunner;
      parts.push(sprite);
      this.startIdle(gunner);
    };

    if (url) {
      const key = textureKeyFor(meta, meta.image_url);
      if (this.textures.exists(key)) {
        register(this.buildGunnerSprite(key, x, y, meta));
      } else {
        const placeholder = this.add.text(x, y, "🪖", { fontSize: "120px" }).setOrigin(0.5).setDepth(10);
        register(placeholder);
        this.load.setCORS("anonymous");
        this.load.image(key, url);
        this.load.once(`filecomplete-image-${key}`, () => {
          // A newer state_sync may have torn this boss down already.
          if (!placeholder.active) return;
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
    const img = buildCharacterObject(this, key, x, y, meta).setDepth(10);
    rememberIdlePose(img, meta, key, GUNNER_TARGET_HEIGHT * meta.scale);
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

    // A sprite sheet animates the arms and face for real, so the faked breath
    // and fist pump would only fight it. Aiming, recoil and flinch still run.
    if (isAnimated(gunner.meta)) return;

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
  private aimAndRecoil(gunner: Gunner, targetY: number, showFireArt = false) {
    const sprite = gunner.sprite;
    // The firing pose covers the swivel; the recoil tween below still runs, so
    // the tank moves whether or not the character has the art.
    if (showFireArt) flashAction(this, sprite as Phaser.GameObjects.Image, gunner.meta, "fire", 420);
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
    const targetBoss = this.gunners[msg.target_side];
    const shooterName = (msg.player.nickname || msg.player.username).toUpperCase();

    // The sender fights on the side they enlisted for, so make sure their own
    // soldier is on the field too.
    this.soldiers.spawnOrGet(msg.player, this.teamColors[msg.player.team], true);

    const muzzle = gunner ? this.muzzleOf(gunner) : { x: CENTER_X, y: CEILING_Y };
    const impact = targetBoss
      ? { x: targetBoss.sprite.x, y: targetBoss.sprite.y }
      : { x: msg.target_side === "A" ? ARENA_WIDTH * 0.26 : ARENA_WIDTH * 0.74, y: CEILING_Y + 200 };

    if (gunner) this.aimAndRecoil(gunner, impact.y, true);

    // Coin price decides how heavy the shell reads on screen.
    const heavy = msg.gift.coins >= 100;
    this.missiles.fireShell(muzzle.x, muzzle.y, impact.x, impact.y, heavy, () => {
      this.bossBars.update(msg.xp.a, msg.xp.b);
      this.effects.floatingNumber(impact.x, impact.y - 60, `-${Math.round(msg.damage)}`, "#ff5b5b");
      if (targetBoss) this.flinch(targetBoss);
    });

    this.audio.missile();
    this.effects.shake(heavy ? 0.012 : 0.006, 180);

    if (msg.combo.count >= 10) {
      this.combos.announce(shooterName, msg.combo.count, msg.combo.tier_label);
      this.audio.combo();
    }

    this.feed.push(
      `${msg.gift.icon} ${shooterName} ${msg.gift.coins}💰 x${msg.quantity} — ${Math.round(msg.damage).toLocaleString("pt-BR")}`
    );

    this.updateArmies(msg.armies);
    if (msg.winner_side) {
      // The server declares the winner the instant the shot resolves, but the
      // shell is still in the air -- let it land before celebrating.
      this.time.delayedCall(600, () => this.showVictory(msg.winner_side as string));
    }
  }

  /** The boss retaliating: a bomb lobbed over the divider onto one active
   * enemy viewer, who takes heavy damage and usually leaves the arena. */
  private handleBossBomb(msg: BossBombMessage) {
    const boss = this.gunners[msg.boss_side];
    const victim = this.soldiers.get(msg.victim.user_id);
    if (!victim) {
      this.updateArmies(msg.armies);
      return;
    }

    const from = boss ? this.muzzleOf(boss) : { x: CENTER_X, y: CEILING_Y };
    const to = { x: victim.sprite.x, y: victim.sprite.y };
    const victimName = msg.victim.username.toUpperCase();

    if (boss) this.aimAndRecoil(boss, to.y, true);

    const bomb = this.add
      .text(from.x, from.y, "💣", { fontSize: "46px" })
      .setOrigin(0.5)
      .setDepth(58);

    // Lobbed in an arc so it reads as a bomb dropping, not a flat shell.
    const path = new Phaser.Curves.QuadraticBezier(
      new Phaser.Math.Vector2(from.x, from.y),
      new Phaser.Math.Vector2((from.x + to.x) / 2, Math.min(from.y, to.y) - 260),
      new Phaser.Math.Vector2(to.x, to.y)
    );
    const travel = { t: 0 };
    this.tweens.add({
      targets: travel,
      t: 1,
      duration: 900,
      ease: "Sine.easeIn",
      onUpdate: () => {
        const point = path.getPoint(travel.t);
        bomb.setPosition(point.x, point.y);
        bomb.rotation += 0.12;
      },
      onComplete: () => {
        bomb.destroy();
        this.effects.flash(to.x, to.y, 70, 0xff9933, 0.95);
        this.effects.burst(to.x, to.y, 0xff6633, 30, 300);
        this.effects.shake(0.02, 240);
        this.audio.missile();

        this.soldiers.setPower(msg.victim.user_id, msg.victim.power);
        this.effects.floatingNumber(to.x, to.y - 34, `-${Math.round(msg.victim.damage)}`, "#ff3b3b");
        if (msg.victim.eliminated) {
          this.soldiers.eliminate(msg.victim.user_id);
          // Both bosses can bomb on the same tick, so each banner goes over
          // its own victim's half instead of stacking in the middle.
          const victimHalfX = msg.boss_side === "A" ? ARENA_WIDTH * 0.75 : ARENA_WIDTH * 0.25;
          this.effects.bannerText(`💣 ${victimName} FOI ATINGIDO!`, victimHalfX, 560, "#ff6b6b", 30);
        }
        this.updateArmies(msg.armies);
      },
    });

    this.feed.push(`💣 ${this.teamNames[msg.boss_side]} BOMBARDEOU ${victimName}`);
  }

  /** Boss reacting to a hit: a quick recoil shudder and a red flash. */
  private flinch(gunner: Gunner) {
    const sprite = gunner.sprite as Phaser.GameObjects.Image;
    // With hurt art the red tint would double up on an already-red drawing.
    const showedHurtArt = flashAction(this, sprite, gunner.meta, "hit", 340);
    this.tweens.add({
      targets: sprite,
      x: gunner.baseX + 10 * gunner.facing,
      duration: 70,
      yoyo: true,
      repeat: 1,
      onComplete: () => sprite.setPosition(gunner.baseX, gunner.baseY),
    });
    if (!showedHurtArt && (sprite as any).setTint) {
      (sprite as any).setTint(0xff8888);
      this.time.delayedCall(140, () => (sprite as any).clearTint?.());
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
