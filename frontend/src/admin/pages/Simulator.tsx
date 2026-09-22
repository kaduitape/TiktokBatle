import { useEffect, useRef, useState } from "react";
import { api, assetUrl } from "../../api/client";

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

/** A gift captured automatically from the LIVE. Simulating one of these
 * replays its real platform ID through the same path a live gift takes. */
interface CatalogGift {
  id: string;
  platform_gift_id: string;
  name: string | null;
  diamond_value: number | null;
  configured: boolean;
  action_label: string | null;
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

/** A saved test viewer: a name and the photo that goes with it. */
interface TestPerson {
  username: string;
  avatar_url: string;
}

const PEOPLE_KEY = "simulator_people";

function loadPeople(): TestPerson[] {
  try {
    const raw = window.localStorage.getItem(PEOPLE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    // Private windows and blocked site data both throw here; the simulator
    // works fine without the saved list.
    return [];
  }
}

function savePeople(people: TestPerson[]): void {
  try {
    window.localStorage.setItem(PEOPLE_KEY, JSON.stringify(people));
  } catch {
    /* not worth interrupting a test over */
  }
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
  const [catalog, setCatalog] = useState<CatalogGift[]>([]);
  const [catalogPick, setCatalogPick] = useState("");
  const photoInput = useRef<HTMLInputElement>(null);
  /** People you registered here, kept in this browser so a round of testing
   * does not mean retyping a name and re-picking a photo every time. */
  const [people, setPeople] = useState<TestPerson[]>(() => loadPeople());
  const [photoBroken, setPhotoBroken] = useState(false);

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
    api
      .get<CatalogGift[]>("/api/live-gifts")
      .then((items) => {
        setCatalog(items);
        if (items[0]) setCatalogPick(items[0].id);
      })
      .catch(() => setCatalog([]));
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

  /** Section 15: no separate path for the simulator. This sends the gift
   * with its real platform ID, so it goes through the normalizer, the
   * catalogue, the streak guard and the rule engine exactly as a live gift
   * does -- which is what makes it a real test of a rule you just saved. */
  const simulateCatalogGift = () =>
    run(async () => {
      const target = await targetSession();
      if (!target) return;
      const entry = catalog.find((c) => c.id === catalogPick);
      if (!entry) return;
      const result = await api.post<{ gift: string; quantity: number }>(
        "/api/simulator/catalog-gift",
        {
          session_id: target.id,
          catalog_id: entry.id,
          username,
          quantity,
          avatar_url: avatarUrl || undefined,
        },
      );
      pushLog(
        `${username} enviou ${result.gift} x${result.quantity} (ID ${entry.platform_gift_id}) para ${target.name}` +
          (entry.configured ? "" : " — ⚠️ este presente ainda não tem ação configurada"),
      );
      refreshAfterEvent();
    });

  const simulateJoin = () =>
    run(async () => {
      const target = await targetSession();
      if (!target) return;
      // The name and photo typed above used to be dropped here, so this
      // button always produced a random stranger with a stranger's face.
      const params = new URLSearchParams({ session_id: target.id });
      if (username.trim()) params.set("username", username.trim());
      if (avatarUrl.trim()) params.set("avatar_url", avatarUrl.trim());
      const result = await api.post<{ username: string }>(`/api/simulator/join?${params}`);
      pushLog(`${result.username} entrou em ${target.name}${avatarUrl ? " (com foto)" : ""}`);
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

  /** Uploading beats pasting a link: the photo ends up on this application's
   * own address, so it does not depend on an outside host still being up, or
   * on that host allowing another site to read its images. */
  const uploadPhoto = (file: File) =>
    run(async () => {
      const { url } = await api.upload("/api/characters/upload", file);
      setAvatarUrl(url);
      pushLog(`Foto carregada para ${username || "o perfil"}.`);
    });

  const rememberPerson = () => {
    const name = username.trim();
    if (!name) return;
    const next = [
      { username: name, avatar_url: avatarUrl.trim() },
      ...people.filter((p) => p.username !== name),
    ].slice(0, 12);
    setPeople(next);
    savePeople(next);
    pushLog(`${name} salvo na lista de perfis.`);
  };

  const forgetPerson = (name: string) => {
    const next = people.filter((p) => p.username !== name);
    setPeople(next);
    savePeople(next);
  };

  const usePerson = (person: TestPerson) => {
    setUsername(person.username);
    setAvatarUrl(person.avatar_url);
  };

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

            <label>Foto do perfil</label>
            <div className="row" style={{ alignItems: "center", gap: 10 }}>
              {avatarUrl ? (
                <img
                  src={assetUrl(avatarUrl)}
                  alt=""
                  className="person-photo"
                  onError={(e) => {
                    // A link that does not load is worth seeing here, not in
                    // the arena as a letter you cannot explain.
                    (e.currentTarget as HTMLImageElement).style.display = "none";
                    setPhotoBroken(true);
                  }}
                  onLoad={() => setPhotoBroken(false)}
                />
              ) : (
                <div className="person-photo placeholder">👤</div>
              )}
              <div style={{ flex: 1 }}>
                <input
                  ref={photoInput}
                  type="file"
                  accept="image/*"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void uploadPhoto(file);
                    e.target.value = "";
                  }}
                />
                <button
                  className="secondary"
                  onClick={() => photoInput.current?.click()}
                  disabled={busy}
                >
                  📁 Carregar foto
                </button>
                {avatarUrl && (
                  <button
                    className="secondary"
                    onClick={() => {
                      setAvatarUrl("");
                      setPhotoBroken(false);
                    }}
                    style={{ marginLeft: 6 }}
                  >
                    Remover
                  </button>
                )}
              </div>
            </div>
            <input
              value={avatarUrl}
              onChange={(e) => {
                setAvatarUrl(e.target.value);
                setPhotoBroken(false);
              }}
              placeholder="ou cole uma URL de imagem"
              style={{ marginTop: 6 }}
            />
            {photoBroken && (
              <p style={{ color: "#e0a01b", fontSize: 12, margin: "4px 0 0" }}>
                Esta imagem não carregou. Sites que bloqueiam o uso da imagem por outra
                página falham também na arena — carregue o arquivo que funciona sempre.
              </p>
            )}

            <div className="row" style={{ marginTop: 10, alignItems: "center" }}>
              <button className="secondary" onClick={rememberPerson} disabled={!username.trim()}>
                💾 Salvar este perfil
              </button>
            </div>
            {people.length > 0 && (
              <div className="people-strip">
                {people.map((person) => (
                  <span key={person.username} className="person-chip">
                    <button
                      className="person-pick"
                      onClick={() => usePerson(person)}
                      title="Usar este perfil"
                    >
                      {person.avatar_url ? (
                        <img src={assetUrl(person.avatar_url)} alt="" />
                      ) : (
                        <span className="person-photo placeholder tiny">👤</span>
                      )}
                      {person.username}
                    </button>
                    <button
                      className="person-remove"
                      onClick={() => forgetPerson(person.username)}
                      title="Remover da lista"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
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
        <h3>Simular presente da LIVE (catálogo automático)</h3>
        <p style={{ color: "#9a9ac0", fontSize: 13 }}>
          Usa o ID real capturado da LIVE e passa pelo mesmo fluxo de um presente de verdade —
          é assim que se testa uma regra recém-salva.
        </p>
        {!catalog.length && (
          <p style={{ color: "#9a9ac0", fontSize: 13 }}>
            Nenhum presente capturado ainda. Envie um presente na LIVE (ou em Presentes da LIVE,
            com o modo aprendizagem ligado) para ele aparecer aqui.
          </p>
        )}
        {catalog.length > 0 && (
          <>
            <div className="form-grid">
              <div>
                <label>Presente capturado</label>
                <select value={catalogPick} onChange={(e) => setCatalogPick(e.target.value)}>
                  {catalog.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.name ?? entry.platform_gift_id} · ID {entry.platform_gift_id}
                      {entry.configured ? ` · ${entry.action_label}` : "  — sem ação"}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label>Quantidade</label>
                <input
                  type="number"
                  min={1}
                  value={quantity}
                  onChange={(e) => setQuantity(Number(e.target.value))}
                />
              </div>
            </div>
            <div className="row" style={{ marginTop: 14 }}>
              <button onClick={simulateCatalogGift} disabled={!session || !catalogPick}>
                SIMULAR PRESENTE DA LIVE
              </button>
            </div>
          </>
        )}
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
