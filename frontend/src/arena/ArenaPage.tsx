import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import PhaserGame from "./game/PhaserGame";

interface SessionOut {
  id: string;
  battle_id: string;
}

interface BattleOut {
  id: string;
}

export default function ArenaPage() {
  const [params] = useSearchParams();
  const [sessionId, setSessionId] = useState<string | null>(null);
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
        const session = await api.post<SessionOut>(`/api/battles/${battleId}/start`);
        if (!cancelled) setSessionId(session.id);
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
      {!error && sessionId && <PhaserGame sessionId={sessionId} />}
      {!error && !sessionId && <div style={{ color: "#888" }}>Carregando arena…</div>}
    </div>
  );
}
