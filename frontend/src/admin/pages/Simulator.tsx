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
  const [battles, setBattles] = useState<Battle[]>([]);
  const [pick, setPick] = useState("");
  const [busy, setBusy] = useState(false);

  /** Simulator actions used to reject silently when something went wrong, so
   * a failure looked like the button doing nothing. */
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
    } catch (err) {
      pushLog(`⚠️ ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

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
    api.get<Battle[]>("/api/battles").then((bs) => {
      setBattles(bs);
      if (bs[0]) setPick(bs[0].id);
    });
    api.get<Gift[]>("/api/gifts").then((items) => {
      setGifts(items);
      if (items[0]) setGiftKey(items[0].gift_key);
    });
  }, []);

  const pushLog = (line: string) => setLog((lines) => [line, ...lines].slice(0, 12));

  /** Starting a session here is what makes the simulator usable on its own:
   * before this, it waited for somebody to open the arena first. */
  const startPicked = () =>
    run(async () => {
      if (!pick) return;
      await api.post(`/api/battles/${pick}/start`);
      await loadActiveBattle();
      pushLog(`Batalha iniciada: ${battles.find((b) => b.id === pick)?.name ?? pick}`);
    });
  const refreshAfterEvent = () => window.setTimeout(() => void loadActiveBattle(), 400);

  const simulateGift = () =>
    run(async () => {
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
    });

  const simulateJoin = () =>
    run(async () => {
      if (!active) return;
      const result = await api.post<{ username: string }>(`/api/simulator/join?session_id=${active.session.id}`);
      pushLog(`${result.username} entrou em ${active.battle.name}`);
    });

  const simulateStress = (count: number) =>
    run(async () => {
      if (!active) return;
      await api.post(
        `/api/simulator/stress?session_id=${active.session.id}&user_count=${count}`,
        gifts.map((gift) => gift.gift_key),
      );
      pushLog(`LIVE lotada em ${active.battle.name}: ${count} usuários`);
      window.setTimeout(() => void loadActiveBattle(), 1500);
    });

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
        <div className="row" style={{ marginTop: 10, alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <label>Iniciar outra batalha e simular nela</label>
            <select value={pick} onChange={(e) => setPick(e.target.value)} style={{ width: "100%" }}>
              {battles.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
          </div>
          <button className="secondary" onClick={startPicked} disabled={busy || !pick}>
            ▶ Iniciar esta
          </button>
        </div>
        <p style={{ color: "#6a6a8a", fontSize: 12, marginTop: 6 }}>
          Iniciar deixa essa batalha como a ativa — é nela que a arena do OBS e o simulador
          passam a trabalhar.
        </p>
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
