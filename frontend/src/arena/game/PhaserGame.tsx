import Phaser from "phaser";
import { useEffect, useRef } from "react";
import GameScene from "./GameScene";
import { ARENA_HEIGHT, ARENA_WIDTH } from "./constants";

export default function PhaserGame({ sessionId }: { sessionId: string }) {
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

    game.scene.add("GameScene", GameScene, true, { sessionId });
    gameRef.current = game;

    return () => {
      game.destroy(true);
      gameRef.current = null;
    };
  }, [sessionId]);

  return <div ref={containerRef} className="arena-canvas-wrap" />;
}
