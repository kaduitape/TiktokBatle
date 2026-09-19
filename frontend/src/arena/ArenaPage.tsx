import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { arenaLayout } from "./game/constants";
import type { BattleMode } from "../types/events";
import PhaserGame from "./game/PhaserGame";

interface SessionOut {
  id: string;
  battle_id: string;
}

interface BattleOut {
  id: string;
  mode?: BattleMode;
}

export default function ArenaPage() {
  const [params] = useSearchParams();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mode, setMode] = useState<BattleMode>("character");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      try {
        let battleId = params.get("battle");
        if (!battleId) {
          const battles = await api.get<BattleOut[]>("/api/battles");
          if (!battles.length) {
            setError("Nenhuma batalha cadastrada. Crie uma no painel admin.");
            return;
          }
          battleId = battles[0].id;
        }
        const battle = await api.get<BattleOut>(`/api/battles/${battleId}`);

        // Read before the scene builds: the ground, the feed and the legend
        // are all measured from the bottom, and they have to know how much of
        // it the live overlay covers before anything is drawn.
        try {
          const layout = await api.get<{ bottom_safe_px?: number }>("/api/settings/arena");
          arenaLayout.bottomSafePx = Math.max(0, Number(layout?.bottom_safe_px ?? 0));
        } catch {
          /* keep the default layout rather than refusing to open the arena */
        }

        const session = await api.post<SessionOut>(`/api/battles/${battleId}/start`);
        if (!cancelled) {
          setMode(battle.mode || "character");
          setSessionId(session.id);
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    }

    boot();
    return () => {
      cancelled = true;
    };
  }, [params]);

  return (
    <div className="arena-viewport">
      {error && <div style={{ color: "#ff8080", padding: 20 }}>{error}</div>}
      {!error && sessionId && <PhaserGame sessionId={sessionId} mode={mode} />}
      {!error && !sessionId && <div style={{ color: "#888" }}>Carregando arena…</div>}
    </div>
  );
}
