import Phaser from "phaser";
import type {
  ArenaMessage,
  PlayerJoinedMessage,
  PvpCombatMessage,
  PvpGiftMessage,
  PvpPlayerPayload,
  StateSyncMessage,
  TeamTotals,
} from "../../types/events";
import { resolveAssetUrl } from "./avatarTexture";
import { setBackground } from "./characterSprite";
import { AudioManager } from "./managers/AudioManager";
import { ComboManager } from "./managers/ComboManager";
import { EffectsManager } from "./managers/EffectsManager";
import { FeedManager } from "./managers/FeedManager";
import { MissileManager } from "./managers/MissileManager";
import { ProjectileManager } from "./managers/ProjectileManager";
import { PvpAvatarManager } from "./managers/PvpAvatarManager";
import { RankingManager } from "./managers/RankingManager";
import { EventSocket } from "./net/EventSocket";
import { ARENA_HEIGHT, ARENA_WIDTH, CEILING_Y, CENTER_X, FLOOR_Y, XP_BAR_Y } from "./constants";

const BAR_WIDTH = ARENA_WIDTH / 2 - 40;
const BAR_HEIGHT = 34;
const MAX_ANIMATED_ATTACKS_PER_TICK = 12;

/** Team PvP arena: the viewers themselves are the fighters. Team A's avatars
 * shoot team B's, each one growing with the gifts its owner sends and dying
 * when its power runs out. Reuses the shared effect/projectile/audio managers
 * so both modes look and sound like the same game. */
export default class TeamBattleScene extends Phaser.Scene {
  private background: Phaser.GameObjects.Image | null = null;
  private sessionId!: string;
  private socket!: EventSocket;

  private avatars!: PvpAvatarManager;
  private effects!: EffectsManager;
  private projectiles!: ProjectileManager;
  private missiles!: MissileManager;
  private combos!: ComboManager;
  private feed!: FeedManager;
  private audio!: AudioManager;
  private ranking: RankingManager | null = null;

  private teamColors: Record<"A" | "B", string> = { A: "#e74c3c", B: "#3498db" };
  private teamNames: Record<"A" | "B", string> = { A: "TIME A", B: "TIME B" };
  private teamBars: Record<"A" | "B", { fill: Phaser.GameObjects.Rectangle; label: Phaser.GameObjects.Text }> =
    {} as any;
  private victoryShown = false;

  constructor() {
    super("TeamBattleScene");
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

    this.add
      .text(24, 40, "A", { fontFamily: "Segoe UI", fontSize: "34px", fontStyle: "bold", color: "#ffd700" })
      .setDepth(90);
    this.add
      .text(ARENA_WIDTH - 24, 40, "B", { fontFamily: "Segoe UI", fontSize: "34px", fontStyle: "bold", color: "#ffd700" })
      .setOrigin(1, 0)
      .setDepth(90);

    this.avatars = new PvpAvatarManager(this);
    this.effects = new EffectsManager(this);
    this.projectiles = new ProjectileManager(this, this.effects);
    this.missiles = new MissileManager(this, this.effects);
    this.combos = new ComboManager(this.effects);
    this.feed = new FeedManager(this);
    this.audio = new AudioManager();
    this.audio.init();

    this.buildTeamBars();

    this.socket = new EventSocket(this.sessionId, (msg) => this.handleMessage(msg));
    this.socket.connect();

    const closeSocket = () => this.socket?.close();
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, closeSocket);
    // game.destroy() tears the scene down without a SHUTDOWN, so without this
    // the socket would outlive the scene and crash on the next message.
    this.events.once(Phaser.Scenes.Events.DESTROY, closeSocket);
  }

  update() {
    this.avatars.syncOverlays();
  }

  private buildTeamBars() {
    (["A", "B"] as const).forEach((team) => {
      const x = team === "A" ? 20 : ARENA_WIDTH - 20 - BAR_WIDTH;
      const bg = this.add.rectangle(x, XP_BAR_Y, BAR_WIDTH, BAR_HEIGHT, 0x000000, 0.55).setOrigin(0, 0.5).setDepth(90);
      bg.setStrokeStyle(2, 0xffffff, 0.4);
      const fill = this.add
        .rectangle(
          x + 2,
          XP_BAR_Y,
          BAR_WIDTH - 4,
          BAR_HEIGHT - 4,
          Phaser.Display.Color.HexStringToColor(this.teamColors[team]).color
        )
        .setOrigin(0, 0.5)
        .setDepth(91);
      this.add
        .text(x + BAR_WIDTH / 2, XP_BAR_Y - 28, this.teamNames[team], {
          fontFamily: "Segoe UI, sans-serif",
          fontSize: "20px",
          fontStyle: "bold",
          color: "#ffffff",
          stroke: "#000",
          strokeThickness: 4,
        })
        .setOrigin(0.5)
        .setDepth(92)
        .setName(`team_name_${team}`);
      const label = this.add
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
      this.teamBars[team] = { fill, label };
    });
  }

  private handleMessage(msg: ArenaMessage) {
    switch (msg.type) {
      case "state_sync":
        this.applyStateSync(msg as StateSyncMessage);
        break;
      case "player_joined":
        this.handleJoin(msg as PlayerJoinedMessage);
        break;
      case "pvp_gift":
        this.handleGift(msg as PvpGiftMessage);
        break;
      case "pvp_combat":
        this.handleCombat(msg as PvpCombatMessage);
        break;
      case "battle_restarted":
        this.victoryShown = false;
        break;
    }
  }

  private applyStateSync(msg: StateSyncMessage) {
    this.teamColors = { A: msg.side_a.team_color, B: msg.side_b.team_color };
    this.teamNames = { A: msg.side_a.name.toUpperCase(), B: msg.side_b.name.toUpperCase() };

    (["A", "B"] as const).forEach((team) => {
      const nameLabel = this.children.getByName(`team_name_${team}`) as Phaser.GameObjects.Text | null;
      nameLabel?.setText(this.teamNames[team]);
      this.teamBars[team].fill.setFillStyle(
        Phaser.Display.Color.HexStringToColor(this.teamColors[team]).color
      );
    });

    this.background = setBackground(
      this,
      resolveAssetUrl(msg.battle.background_url),
      ARENA_WIDTH,
      ARENA_HEIGHT,
      this.background
    );

    if (!this.ranking) this.ranking = new RankingManager(this, msg.session_id);

    for (const player of msg.players) {
      if (player.eliminated) continue;
      this.avatars.spawnOrGet(player, this.teamColors[player.team], false);
    }
    this.updateTeamBars(msg.teams);
  }

  private handleJoin(msg: PlayerJoinedMessage) {
    const player = msg.player as PvpPlayerPayload;
    this.avatars.spawnOrGet(player, this.teamColors[player.team], true).then(() => {
      const name = (player.nickname || player.username).toUpperCase();
      this.effects.joinToast(`${name} ENTROU NO TIME ${player.team}`, ARENA_WIDTH / 2, 700);
    });
  }

  private async handleGift(msg: PvpGiftMessage) {
    const fighter = await this.avatars.spawnOrGet(msg.player, this.teamColors[msg.player.team], true);

    this.avatars.setPower(msg.player.user_id, msg.growth.power);
    this.avatars.celebrateGrowth(msg.player.user_id, msg.growth.leveled_up);

    const displayName = (msg.player.nickname || msg.player.username).toUpperCase();
    this.effects.floatingNumber(
      fighter.sprite.x,
      fighter.sprite.y - fighter.diameter / 2 - 40,
      `+${Math.round(msg.growth.gained)}`,
      "#7dd3fc"
    );

    if (msg.growth.leveled_up) {
      this.effects.bannerText(`${displayName} SUBIU PARA NÍVEL ${msg.growth.level}`, ARENA_WIDTH / 2, 560, "#ffd700", 32);
    }

    if (msg.attack) {
      this.animateStrike(msg.player.user_id, msg.attack.target_user_id, msg.gift, msg.attack, true);
    }

    if (msg.combo.count >= 10) {
      this.combos.announce(displayName, msg.combo.count, msg.combo.tier_label);
      this.audio.combo();
    }

    this.feed.push(`${msg.gift.icon} ${displayName} x${msg.quantity} +${Math.round(msg.growth.gained)}`);
    this.updateTeamBars(msg.teams);
    if (msg.winner_side) this.showVictory(msg.winner_side);
  }

  private handleCombat(msg: PvpCombatMessage) {
    // A tick can carry dozens of exchanges. Animating every one buries the
    // arena in projectiles, so only a slice gets a visible shot -- the rest
    // still apply their damage, just silently.
    msg.attacks.forEach((attack, index) => {
      if (index < MAX_ANIMATED_ATTACKS_PER_TICK) {
        this.animateStrike(attack.attacker_user_id, attack.target_user_id, null, attack, false);
        return;
      }
      this.avatars.setPower(attack.target_user_id, attack.target_power);
      if (attack.eliminated) this.avatars.eliminate(attack.target_user_id);
    });
    this.updateTeamBars(msg.teams);
    if (msg.winner_side) this.showVictory(msg.winner_side);
  }

  private animateStrike(
    attackerUserId: string,
    targetUserId: string,
    gift: PvpGiftMessage["gift"] | null,
    attack: { damage: number; target_power: number; eliminated: boolean },
    fromGift: boolean
  ) {
    const attacker = this.avatars.get(attackerUserId);
    const target = this.avatars.get(targetUserId);
    if (!attacker || !target) return;

    const from = { x: attacker.sprite.x, y: attacker.sprite.y };
    const to = { x: target.sprite.x, y: target.sprite.y };

    const onImpact = () => {
      this.avatars.setPower(targetUserId, attack.target_power);
      // Routine tick hits skip the damage number: with dozens per tick the
      // screen turns into a wall of red text.
      if (fromGift || attack.eliminated) {
        this.effects.floatingNumber(to.x, to.y - 30, `-${Math.round(attack.damage)}`, "#ff5b5b");
      }
      if (attack.eliminated) {
        this.effects.burst(to.x, to.y, 0xff4444, 26, 240);
        this.avatars.eliminate(targetUserId);
      }
    };

    const heavy = fromGift && (gift?.action_type === "missile" || gift?.action_type === "special");
    if (heavy) {
      this.missiles.fireMissile(from.x, from.y, to.x, to.y, attack.eliminated, onImpact);
      this.audio.missile();
    } else {
      this.projectiles.fireShot(from.x, from.y, to.x, to.y, onImpact, 0, !fromGift);
      if (fromGift) this.audio.shot();
    }
  }

  private updateTeamBars(teams: TeamTotals) {
    const total = Math.max(1, teams.A.power + teams.B.power);
    (["A", "B"] as const).forEach((team) => {
      const bar = this.teamBars[team];
      if (!bar) return;
      const pct = Phaser.Math.Clamp(teams[team].power / total, 0, 1);
      this.tweens.add({
        targets: bar.fill,
        width: Math.max(2, (BAR_WIDTH - 4) * pct),
        duration: 350,
        ease: "Cubic.easeOut",
      });
      bar.label.setText(
        `⚔️ ${Math.round(teams[team].power).toLocaleString("pt-BR")} · ${teams[team].alive} vivos`
      );
    });
  }

  private showVictory(side: string) {
    if (this.victoryShown) return;
    this.victoryShown = true;
    this.audio.victoryFanfare();
    this.effects.bannerText("🏆 VITÓRIA!", ARENA_WIDTH / 2, ARENA_HEIGHT / 2 - 60, "#ffd700", 64);
    this.effects.bannerText(
      this.teamNames[side as "A" | "B"],
      ARENA_WIDTH / 2,
      ARENA_HEIGHT / 2 + 10,
      "#ffffff",
      40
    );

    for (const fighter of this.avatars.aliveOf(side as "A" | "B")) {
      this.tweens.add({
        targets: fighter.sprite,
        y: fighter.sprite.y - 60,
        duration: 300,
        yoyo: true,
        repeat: 3,
        ease: "Sine.easeOut",
      });
    }
  }
}
