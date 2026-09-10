import { useEffect, useState } from "react";
import { api } from "../../api/client";

interface Battle {
  id: string;
  name: string;
}

interface Gift {
  id: string;
  gift_key: string;
  name: string;
  icon: string;
}

interface Session {
  id: string;
  side_a_xp: number;
  side_b_xp: number;
  status: string;
}

export default function Simulator() {
  const [battles, setBattles] = useState<Battle[]>([]);
  const [gifts, setGifts] = useState<Gift[]>([]);
  const [battleId, setBattleId] = useState("");
  const [session, setSession] = useState<Session | null>(null);

  const [username, setUsername] = useState("carlos");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [giftKey, setGiftKey] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [log, setLog] = useState<string[]>([]);

  useEffect(() => {
    api.get<Battle[]>("/api/battles").then((bs) => {
      setBattles(bs);
      if (bs[0]) setBattleId(bs[0].id);
    });
    api.get<Gift[]>("/api/gifts").then((gs) => {
      setGifts(gs);
      if (gs[0]) setGiftKey(gs[0].gift_key);
    });
  }, []);

  useEffect(() => {
    if (!battleId) return;
    api.post<Session>(`/api/battles/${battleId}/start`).then(setSession);
  }, [battleId]);

  const refreshSession = () => {
    if (battleId) api.get<Session>(`/api/battles/${battleId}/session`).then(setSession);
  };

  const pushLog = (line: string) => setLog((l) => [line, ...l].slice(0, 12));

  const simulateGift = async () => {
    if (!session) return;
    await api.post("/api/simulator/gift", {
      session_id: session.id,
      username,
      avatar_url: avatarUrl || undefined,
      gift_key: giftKey,
      quantity,
    });
    pushLog(`${username} enviou ${giftKey} x${quantity}`);
    setTimeout(refreshSession, 400);
  };

  const simulateJoin = async () => {
    if (!session) return;
    const res = await api.post<{ username: string }>(`/api/simulator/join?session_id=${session.id}`);
    pushLog(`${res.username} entrou na live`);
  };

  const simulateStress = async (count: number) => {
    if (!session) return;
    await api.post(
      `/api/simulator/stress?session_id=${session.id}&user_count=${count}`,
      gifts.map((g) => g.gift_key)
    );
    pushLog(`🔥 LIVE LOTADA: gerando ${count} usuários`);
    setTimeout(refreshSession, 1500);
  };

  return (
    <div>
      <h1>Simulador</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Executa exatamente o mesmo pipeline de um evento real do TikTok — sem lógica de animação separada.
      </p>

      <div className="card">
        <label>Batalha</label>
        <select value={battleId} onChange={(e) => setBattleId(e.target.value)}>
          {battles.map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>
        {session && (
          <div className="row" style={{ marginTop: 10 }}>
            <span className="pill">Lado A: {Math.round(session.side_a_xp).toLocaleString("pt-BR")}</span>
            <span className="pill">Lado B: {Math.round(session.side_b_xp).toLocaleString("pt-BR")}</span>
            <span className="pill">Status: {session.status}</span>
            <a href={`#/arena?battle=${battleId}`} target="_blank" rel="noreferrer">
              <button className="secondary">Abrir arena para ver ao vivo</button>
            </a>
          </div>
        )}
      </div>

      <div className="card">
        <h3>▶ Simular Presente</h3>
        <div className="form-grid">
          <div>
            <label>Usuário</label>
            <input value={username} onChange={(e) => setUsername(e.target.value)} />
            <label>Avatar (URL, opcional)</label>
            <input value={avatarUrl} onChange={(e) => setAvatarUrl(e.target.value)} placeholder="https://i.pravatar.cc/150?u=carlos" />
          </div>
          <div>
            <label>Presente</label>
            <select value={giftKey} onChange={(e) => setGiftKey(e.target.value)}>
              {gifts.map((g) => (
                <option key={g.id} value={g.gift_key}>{g.icon} {g.name}</option>
              ))}
            </select>
            <label>Quantidade</label>
            <input type="number" min={1} value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} />
          </div>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button onClick={simulateGift}>▶ SIMULAR PRESENTE</button>
          <button className="secondary" onClick={simulateJoin}>👤 Simular novo espectador</button>
        </div>
      </div>

      <div className="card">
        <h3>🔥 Teste de estresse — LIVE lotada</h3>
        <div className="row">
          {[100, 250, 500, 1000].map((n) => (
            <button key={n} className="secondary" onClick={() => simulateStress(n)}>
              {n} usuários
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>Log</h3>
        {log.map((l, i) => (
          <div key={i} style={{ fontSize: 13, color: "#b6b6d0" }}>{l}</div>
        ))}
      </div>
    </div>
  );
}
