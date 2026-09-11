import { useEffect, useState } from "react";
import { api } from "../../api/client";

interface Battle {
  id: string;
  name: string;
}

interface Session {
  id: string;
}

export default function Live() {
  const [battles, setBattles] = useState<Battle[]>([]);
  const [battleId, setBattleId] = useState("");
  const [session, setSession] = useState<Session | null>(null);
  const [username, setUsername] = useState("");
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Battle[]>("/api/battles").then((bs) => {
      setBattles(bs);
      if (bs[0]) setBattleId(bs[0].id);
    });
  }, []);

  useEffect(() => {
    if (!battleId) return;
    api.post<Session>(`/api/battles/${battleId}/start`).then(setSession);
  }, [battleId]);

  const refreshStatus = () => {
    if (!session) return;
    api.get<{ connected: boolean }>(`/api/live/${session.id}/status`).then((s) => setConnected(s.connected));
  };

  useEffect(() => {
    refreshStatus();
    const id = setInterval(refreshStatus, 5000);
    return () => clearInterval(id);
  }, [session]);

  const connect = async () => {
    if (!session || !username) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/live/${session.id}/connect`, { tiktok_username: username });
      setTimeout(refreshStatus, 1500);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    if (!session) return;
    setBusy(true);
    try {
      await api.post(`/api/live/${session.id}/disconnect`);
      setTimeout(refreshStatus, 500);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h1>Live</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Conecta a arena a uma TikTok LIVE real, usando o mesmo pipeline do simulador.
      </p>

      <div className="card">
        <label>Batalha</label>
        <select value={battleId} onChange={(e) => setBattleId(e.target.value)}>
          {battles.map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>

        <label>Usuário do TikTok (sem @)</label>
        <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="seuusuario" />

        <div className="row" style={{ marginTop: 14 }}>
          <span className="pill">{connected ? "🟢 conectado" : "⚪ desconectado"}</span>
          {!connected && (
            <button onClick={connect} disabled={busy || !username}>
              Conectar
            </button>
          )}
          {connected && (
            <button className="secondary" onClick={disconnect} disabled={busy}>
              Desconectar
            </button>
          )}
        </div>

        {error && (
          <p style={{ color: "#ff8080", fontSize: 12, marginTop: 10 }}>
            {error}
            <br />
            Verifique se o pacote <code>TikTokLive</code> está instalado no backend (opcional, ver README) e se o
            usuário está com uma LIVE ativa no momento.
          </p>
        )}
      </div>
    </div>
  );
}
