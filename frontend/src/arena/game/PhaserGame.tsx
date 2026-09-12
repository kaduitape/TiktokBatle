import Phaser from "phaser";
import { useEffect, useRef } from "react";
import type { BattleMode } from "../../types/events";
import GameScene from "./GameScene";
import TankWarScene from "./TankWarScene";
import TeamBattleScene from "./TeamBattleScene";
import { ARENA_HEIGHT, ARENA_WIDTH } from "./constants";

export default function PhaserGame({
  sessionId,
  mode = "character",
}: {
  sessionId: string;
  mode?: BattleMode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const gameRef = useRef<Phaser.Game | null>(null);

  useEffect(() => {
    if (!containerRef.current || gameRef.current) return;

    const game = new Phaser.Game({
      type: Phaser.AUTO,
      parent: containerRef.current,
      width: ARENA_WIDTH,
      height: ARENA_HEIGHT,
      backgroundColor: "#0b0b12",
      scale: {
        mode: Phaser.Scale.FIT,
        autoCenter: Phaser.Scale.CENTER_BOTH,
      },
      physics: {
        default: "matter",
        matter: {
          gravity: { x: 0, y: 1.1 },
          debug: false,
        },
      },
    });

    if (mode === "team_pvp") {
      game.scene.add("TeamBattleScene", TeamBattleScene, true, { sessionId });
    } else if (mode === "tank_war") {
      game.scene.add("TankWarScene", TankWarScene, true, { sessionId });
    } else {
      game.scene.add("GameScene", GameScene, true, { sessionId });
    }
    gameRef.current = game;

    return () => {
      game.destroy(true);
      gameRef.current = null;
    };
  }, [sessionId, mode]);

  return <div ref={containerRef} className="arena-canvas-wrap" />;
}
