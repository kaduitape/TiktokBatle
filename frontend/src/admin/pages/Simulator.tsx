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
  /** Gift keys this battle accepts. Empty means it accepts all of them. */
  const [allowed, setAllowed] = useState<string[]>([]);

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
      // Follow the live battle unless the admin has already picked another.
      setPick((p) => p || current.battle.id);
      return current;
    } catch {
      setActive(null);
      setActiveError("Nenhuma batalha está em andamento. Escolha uma abaixo e clique em iniciar.");
      return null;
    }
  };

  /** The session the buttons actually send to.
   *
   * This used to be whichever battle was started most recently, which is not
   * necessarily the one open in OBS -- so events landed somewhere the admin
   * could not see and the simulator looked broken. Now it is the battle
   * selected here, started if it is not running yet. */
  const targetSession = async (): Promise<{ id: string; name: string } | null> => {
    const battle = battles.find((b) => b.id === pick);
    if (!battle) return null;
    if (active?.battle.id === battle.id) return { id: active.session.id, name: battle.name };
    const session = await api.post<{ id: string }>(`/api/battles/${battle.id}/start`);
    await loadActiveBattle();
    return { id: session.id, name: battle.name };
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

  // A battle can be limited to a few gifts. Sending one outside that list is
  // accepted and then ignored by the game, which is invisible from here --
  // so read the selection and say which gifts actually count.
  useEffect(() => {
    if (!pick || !gifts.length) return;
    api
      .get<{ gift_ids: string[] }>(`/api/battles/${pick}/gifts`)
      .then((sel) => {
        const keys = gifts.filter((g) => sel.gift_ids.includes(g.id)).map((g) => g.gift_key);
        setAllowed(keys);
        if (keys.length && !keys.includes(giftKey)) setGiftKey(keys[0]);
      })
      .catch(() => setAllowed([]));
  }, [pick, gifts]);

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
      const target = await targetSession();
      if (!target) return;
      if (allowed.length && !allowed.includes(giftKey)) {
        pushLog(`⚠️ "${giftKey}" não está na seleção de presentes desta batalha — não vale nada nela.`);
        return;
      }
      await api.post("/api/simulator/gift", {
        session_id: target.id,
        username,
        avatar_url: avatarUrl || undefined,
        gift_key: giftKey,
        quantity,
      });
      pushLog(`${username} enviou ${giftKey} x${quantity} para ${target.name}`);
      refreshAfterEvent();
    });

  const simulateJoin = () =>
    run(async () => {
      const target = await targetSession();
      if (!target) return;
      const result = await api.post<{ username: string }>(`/api/simulator/join?session_id=${target.id}`);
      pushLog(`${result.username} entrou em ${target.name}`);
    });

  const simulateStress = (count: number) =>
    run(async () => {
      const target = await targetSession();
      if (!target) return;
      await api.post(
        `/api/simulator/stress?session_id=${target.id}&user_count=${count}`,
        (allowed.length ? gifts.filter((g) => allowed.includes(g.gift_key)) : gifts).map((g) => g.gift_key),
      );
      pushLog(`LIVE lotada em ${target.name}: ${count} usuários`);
      window.setTimeout(() => void loadActiveBattle(), 1500);
    });

  const session = active?.session;

  return (
    <div>
      <h1>Simulador</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Os eventos usam o mesmo pipeline do TikTok LIVE e vão para a batalha escolhida abaixo —
        se ela não estiver rodando, é iniciada na hora.
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
            <label>Simular nesta batalha</label>
            <select value={pick} onChange={(e) => setPick(e.target.value)} style={{ width: "100%" }}>
              {battles.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}{active?.battle.id === b.id ? "  (em andamento)" : ""}
                </option>
              ))}
            </select>
          </div>
          <button className="secondary" onClick={startPicked} disabled={busy || !pick}>
            ▶ Iniciar esta
          </button>
        </div>
        {pick && active && active.battle.id !== pick && (
          <p style={{ color: "#e0a01b", fontSize: 12, marginTop: 6 }}>
            A batalha em andamento é "{active.battle.name}". Simular aqui vai iniciar
            "{battles.find((b) => b.id === pick)?.name}" e passar a transmissão para ela —
            confira qual está aberta no OBS.
          </p>
        )}
        {allowed.length > 0 && (
          <p style={{ color: "#9a9ac0", fontSize: 12, marginTop: 6 }}>
            Esta batalha aceita só {allowed.length} presente(s). Os demais são entregues e
            ignorados pelo jogo.
          </p>
        )}
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
              {gifts.map((gift) => {
                const counts = !allowed.length || allowed.includes(gift.gift_key);
                return (
                  <option key={gift.id} value={gift.gift_key}>
                    {gift.icon} {gift.name}{counts ? "" : "  — não vale nesta batalha"}
                  </option>
                );
              })}
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
