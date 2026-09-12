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

interface ActiveBattle {
  battle: Battle;
  session: Session;
}

export default function Simulator() {
  const [gifts, setGifts] = useState<Gift[]>([]);
  const [active, setActive] = useState<ActiveBattle | null>(null);
  const [activeError, setActiveError] = useState<string | null>(null);

  const [username, setUsername] = useState("carlos");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [giftKey, setGiftKey] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [log, setLog] = useState<string[]>([]);

  const loadActiveBattle = async () => {
    try {
      const current = await api.get<ActiveBattle>("/api/battles/active");
      setActive(current);
      setActiveError(null);
    } catch {
      setActive(null);
      setActiveError("Nenhuma batalha está ativa. Abra a arena da batalha que deseja transmitir e volte aqui.");
    }
  };

  useEffect(() => {
    void loadActiveBattle();
    api.get<Gift[]>("/api/gifts").then((items) => {
      setGifts(items);
      if (items[0]) setGiftKey(items[0].gift_key);
    });
  }, []);

  const pushLog = (line: string) => setLog((lines) => [line, ...lines].slice(0, 12));
  const refreshAfterEvent = () => window.setTimeout(() => void loadActiveBattle(), 400);

  const simulateGift = async () => {
    if (!active) return;
    await api.post("/api/simulator/gift", {
      session_id: active.session.id,
      username,
      avatar_url: avatarUrl || undefined,
      gift_key: giftKey,
      quantity,
    });
    pushLog(`${username} enviou ${giftKey} x${quantity} para ${active.battle.name}`);
    refreshAfterEvent();
  };

  const simulateJoin = async () => {
    if (!active) return;
    const result = await api.post<{ username: string }>(`/api/simulator/join?session_id=${active.session.id}`);
    pushLog(`${result.username} entrou em ${active.battle.name}`);
  };

  const simulateStress = async (count: number) => {
    if (!active) return;
    await api.post(
      `/api/simulator/stress?session_id=${active.session.id}&user_count=${count}`,
      gifts.map((gift) => gift.gift_key),
    );
    pushLog(`LIVE lotada em ${active.battle.name}: ${count} usuários`);
    window.setTimeout(() => void loadActiveBattle(), 1500);
  };

  const session = active?.session;

  return (
    <div>
      <h1>Simulador</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Os eventos usam o mesmo pipeline do TikTok LIVE e chegam somente à batalha ativa na arena/OBS.
      </p>

      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <label>Batalha ativa</label>
            <strong style={{ display: "block", marginTop: 4 }}>{active?.battle.name || "Nenhuma batalha ativa"}</strong>
          </div>
          <button className="secondary" onClick={() => void loadActiveBattle()}>Atualizar</button>
        </div>
        {activeError && <p style={{ color: "#ff8080", fontSize: 13 }}>{activeError}</p>}
        {session && (
          <div className="row" style={{ marginTop: 10 }}>
            <span className="pill">Lado A: {Math.round(session.side_a_xp).toLocaleString("pt-BR")}</span>
            <span className="pill">Lado B: {Math.round(session.side_b_xp).toLocaleString("pt-BR")}</span>
            <span className="pill">Status: {session.status}</span>
            <a href={`#/arena?battle=${active?.battle.id}`} target="_blank" rel="noreferrer">
              <button className="secondary">Abrir arena ativa</button>
            </a>
          </div>
        )}
      </div>

      <div className="card">
        <h3>Simular presente</h3>
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
              {gifts.map((gift) => (
                <option key={gift.id} value={gift.gift_key}>{gift.icon} {gift.name}</option>
              ))}
            </select>
            <label>Quantidade</label>
            <input type="number" min={1} value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} />
          </div>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button onClick={simulateGift} disabled={!session || !giftKey}>SIMULAR PRESENTE</button>
          <button className="secondary" onClick={simulateJoin} disabled={!session}>Simular novo espectador</button>
        </div>
      </div>

      <div className="card">
        <h3>Teste de estresse — LIVE lotada</h3>
        <div className="row">
          {[100, 250, 500, 1000].map((count) => (
            <button key={count} className="secondary" onClick={() => simulateStress(count)} disabled={!session}>
              {count} usuários
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>Log</h3>
        {log.map((line, index) => (
          <div key={index} style={{ fontSize: 13, color: "#b6b6d0" }}>{line}</div>
        ))}
      </div>
    </div>
  );
}
