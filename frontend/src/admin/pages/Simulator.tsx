import { useEffect, useState } from "react";
import { api, assetUrl } from "../../api/client";

interface Battle {
  id: string;
  name: string;
  mode: "character" | "team_pvp" | "tank_war";
  background_url: string | null;
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

interface SimulatorProfile {
  id: string;
  name: string;
  avatar_url: string;
}

interface AutoStatus {
  session_id: string;
  running: boolean;
  team_a_limit?: number;
  team_b_limit?: number;
  team_a_joined?: number;
  team_b_joined?: number;
  pending?: number;
  profiles_exhausted?: boolean;
  shortfall?: number;
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
  const [allowed, setAllowed] = useState<string[]>([]);
  const [profiles, setProfiles] = useState<SimulatorProfile[]>([]);
  /** Said next to the button. The log is a thousand pixels further down,
   * so a failure reported only there looks like a button that does
   * nothing. */
  const [profileNote, setProfileNote] = useState<{ bad: boolean; text: string } | null>(null);
  /** How many gifts each simulated viewer throws at the rival boss. */
  const [attacksEach, setAttacksEach] = useState(2);
  const [selectedProfiles, setSelectedProfiles] = useState<string[]>([]);
  const [profileName, setProfileName] = useState("");
  const [profileFile, setProfileFile] = useState<File | null>(null);
  const [autoRunning, setAutoRunning] = useState(false);
  const [autoStatus, setAutoStatus] = useState<AutoStatus | null>(null);
  const [teamACount, setTeamACount] = useState(4);
  const [teamBCount, setTeamBCount] = useState(4);
  const [arenaBackground, setArenaBackground] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<CatalogGift[]>([]);
  const [catalogPick, setCatalogPick] = useState("");

  const pushLog = (line: string) => setLog((lines) => [line, ...lines].slice(0, 12));

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
      setArenaBackground(current.battle.background_url);
      setActiveError(null);
      setPick((previous) => previous || current.battle.id);
      return current;
    } catch {
      setActive(null);
      setAutoRunning(false);
      setActiveError("Nenhuma batalha está em andamento. Escolha uma abaixo e clique em iniciar.");
      return null;
    }
  };

  const loadProfiles = async () => {
    const stored = await api.get<SimulatorProfile[]>("/api/simulator/profiles");
    setProfiles(stored);
    setSelectedProfiles((current) => current.length
      ? current.filter((id) => stored.some((profile) => profile.id === id))
      : stored.map((profile) => profile.id));
  };

  /** Ensures every simulator control targets the same session OBS is using. */
  const targetSession = async (): Promise<{ id: string; name: string; battleId: string; mode: Battle["mode"] } | null> => {
    const battle = battles.find((item) => item.id === pick);
    if (!battle) return null;
    if (active?.battle.id === battle.id) {
      return { id: active.session.id, name: battle.name, battleId: battle.id, mode: battle.mode };
    }
    const session = await api.post<Session>(`/api/battles/${battle.id}/start`);
    setActive({ battle, session });
    setArenaBackground(battle.background_url);
    return { id: session.id, name: battle.name, battleId: battle.id, mode: battle.mode };
  };

  useEffect(() => {
    void loadActiveBattle();
    void loadProfiles();
    api.get<Battle[]>("/api/battles").then((items) => {
      setBattles(items);
      if (items[0]) setPick((current) => current || items[0].id);
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

  useEffect(() => {
    if (!pick || !gifts.length) return;
    api
      .get<{ gift_ids: string[] }>(`/api/battles/${pick}/gifts`)
      .then((selection) => {
        const keys = gifts.filter((gift) => selection.gift_ids.includes(gift.id)).map((gift) => gift.gift_key);
        setAllowed(keys);
        if (keys.length && !keys.includes(giftKey)) setGiftKey(keys[0]);
      })
      .catch(() => setAllowed([]));
  }, [pick, gifts]);

  useEffect(() => {
    if (!active?.session.id) return;
    let cancelled = false;
    const loadStatus = () => api
      .get<AutoStatus>(`/api/simulator/auto?session_id=${encodeURIComponent(active.session.id)}`)
      .then((status) => {
        if (cancelled) return;
        setAutoStatus(status);
        setAutoRunning(status.running);
        if (status.running) {
          if (status.team_a_limit !== undefined) setTeamACount(status.team_a_limit);
          if (status.team_b_limit !== undefined) setTeamBCount(status.team_b_limit);
        }
      })
      .catch(() => {
        if (!cancelled) setAutoRunning(false);
      });
    void loadStatus();
    const timer = window.setInterval(loadStatus, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [active?.session.id]);

  const startPicked = () => run(async () => {
    const target = await targetSession();
    if (target) pushLog(`Batalha iniciada: ${target.name}`);
  });

  const refreshAfterEvent = () => window.setTimeout(() => void loadActiveBattle(), 400);

  const simulateGift = () => run(async () => {
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

  const simulateJoin = () => run(async () => {
    const target = await targetSession();
    if (!target) return;
    const profileId = selectedProfiles[0];
    const query = new URLSearchParams({ session_id: target.id, username });
    if (profileId) query.set("profile_id", profileId);
    const result = await api.post<{ username: string; team: string | null }>(`/api/simulator/join?${query}`);
    pushLog(`${result.username} entrou${result.team ? ` no time ${result.team}` : ""} em ${target.name}`);
  });

  const simulateLike = () => run(async () => {
    const target = await targetSession();
    if (!target) return;
    const result = await api.post<{ username: string; count: number }>("/api/simulator/like", {
      session_id: target.id,
      username,
      avatar_url: avatarUrl || undefined,
      profile_id: selectedProfiles[0] || undefined,
      count: quantity,
    });
    pushLog(`${result.username} mandou ${result.count} ${result.count === 1 ? "coração" : "corações"} para o próprio time`);
    refreshAfterEvent();
  });

  const simulateFollow = () => run(async () => {
    const target = await targetSession();
    if (!target) return;
    const result = await api.post<{ username: string }>("/api/simulator/follow", {
      session_id: target.id,
      username,
      avatar_url: avatarUrl || undefined,
      profile_id: selectedProfiles[0] || undefined,
    });
    pushLog(`${result.username} seguiu: avatar maior e vida triplicada`);
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

  const simulateStress = (count: number) => run(async () => {
    const target = await targetSession();
    if (!target) return;
    const result = await api.post<{ spawned: number; returning: number; attacks: number }>(
      `/api/simulator/stress?session_id=${target.id}&user_count=${count}&attacks_each=${attacksEach}`,
      (allowed.length ? gifts.filter((gift) => allowed.includes(gift.gift_key)) : gifts).map((gift) => gift.gift_key),
    );
    pushLog(
      `LIVE lotada em ${target.name}: ${result.spawned} entraram` +
        (result.returning ? ` (${result.returning} voltaram após serem eliminados)` : "") +
        ` · ${result.attacks} ataques ao chefão rival`,
    );
    window.setTimeout(() => void loadActiveBattle(), 1500);
  });

  /** A stress test leaves its crowd behind, and the next one piles more on
   * top. This empties the arena before starting over. */
  const resetArena = () => run(async () => {
    const target = await targetSession();
    if (!target) return;
    if (!window.confirm(`Tirar todo mundo da arena de "${target.name}" e recomeçar a batalha?`)) return;
    const result = await api.post<{ removed: number }>("/api/simulator/reset", {
      session_id: target.id,
      restart_battle: true,
    });
    pushLog(`Arena de ${target.name} limpa: ${result.removed} perfis removidos, batalha reiniciada.`);
    await loadActiveBattle();
  });

  const addProfile = async () => {
    setProfileNote(null);
    setBusy(true);
    try {
      // The button used to sit disabled until a file was chosen, which from
      // the other side of the screen is indistinguishable from a broken one.
      if (!profileFile) {
        throw new Error('Escolha a foto da pessoa em "Foto do perfil" antes de cadastrar.');
      }
      const uploaded = await api.upload("/api/simulator/upload", profileFile);
      const profile = await api.post<SimulatorProfile>("/api/simulator/profiles", {
        name: profileName.trim() || profileFile.name.replace(/\.[^/.]+$/, ""),
        avatar_url: uploaded.url,
      });
      setProfiles((items) => [profile, ...items]);
      setSelectedProfiles((ids) => [...ids, profile.id]);
      setProfileFile(null);
      setProfileName("");
      setProfileNote({ bad: false, text: `${profile.name} cadastrado.` });
      pushLog(`Perfil ${profile.name} cadastrado no simulador.`);
    } catch (err) {
      const text = err instanceof Error ? err.message : String(err);
      setProfileNote({ bad: true, text });
      pushLog(`⚠️ ${text}`);
    } finally {
      setBusy(false);
    }
  };

  const removeProfile = (profile: SimulatorProfile) => run(async () => {
    await api.del(`/api/simulator/profiles/${profile.id}`);
    setProfiles((items) => items.filter((item) => item.id !== profile.id));
    setSelectedProfiles((ids) => ids.filter((id) => id !== profile.id));
  });

  const toggleProfile = (id: string) => setSelectedProfiles((ids) =>
    ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]);

  const startAuto = () => run(async () => {
    const target = await targetSession();
    if (!target) return;
    const status = await api.post<AutoStatus & { profiles: number }>("/api/simulator/auto/start", {
      session_id: target.id,
      profile_ids: selectedProfiles,
      team_a_count: teamACount,
      team_b_count: teamBCount,
    });
    setAutoStatus(status);
    setAutoRunning(status.running);
    pushLog(
      `Simulação ligada em ${target.name}: até ${teamACount} no lado A e ${teamBCount} no lado B.` +
      (status.shortfall ? ` Faltam ${status.shortfall} perfil(is); ela vai parar de preencher quando acabarem.` : ""),
    );
  });

  const stopAuto = () => run(async () => {
    const sessionId = active?.session.id;
    if (!sessionId) return;
    await api.post(`/api/simulator/auto/stop?session_id=${encodeURIComponent(sessionId)}`);
    setAutoRunning(false);
    setAutoStatus({ session_id: sessionId, running: false });
    pushLog("Simulação contínua pausada.");
  });

  const uploadArenaBackground = (file: File) => run(async () => {
    const target = await targetSession();
    if (!target) return;
    const uploaded = await api.upload("/api/simulator/upload", file);
    await api.put(`/api/battles/${target.battleId}/background`, { background_url: uploaded.url });
    setArenaBackground(uploaded.url);
    setBattles((items) => items.map((battle) => battle.id === target.battleId ? { ...battle, background_url: uploaded.url } : battle));
    setActive((current) => current && current.battle.id === target.battleId
      ? { ...current, battle: { ...current.battle, background_url: uploaded.url } }
      : current);
    pushLog("Imagem de fundo aplicada à arena aberta.");
  });

  const clearArenaBackground = () => run(async () => {
    const target = await targetSession();
    if (!target) return;
    await api.put(`/api/battles/${target.battleId}/background`, { background_url: null });
    setArenaBackground(null);
    setBattles((items) => items.map((battle) => battle.id === target.battleId ? { ...battle, background_url: null } : battle));
    setActive((current) => current && current.battle.id === target.battleId
      ? { ...current, battle: { ...current.battle, background_url: null } }
      : current);
    pushLog("Imagem de fundo removida da arena.");
  });

  const session = active?.session;

  return (
    <div>
      <h1>Simulador</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Os eventos entram na mesma fila da LIVE. A simulação contínua alterna chegadas e presentes em ritmo variável, sem criar uma animação paralela.
      </p>

      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div><label>Batalha ativa</label><strong style={{ display: "block", marginTop: 4 }}>{active?.battle.name || "Nenhuma batalha ativa"}</strong></div>
          <button className="secondary" onClick={() => void loadActiveBattle()}>Atualizar</button>
        </div>
        {activeError && <p style={{ color: "#ff8080", fontSize: 13 }}>{activeError}</p>}
        <div className="row" style={{ marginTop: 10, alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <label>Simular nesta batalha</label>
            <select value={pick} onChange={(event) => setPick(event.target.value)} style={{ width: "100%" }}>
              {battles.map((battle) => <option key={battle.id} value={battle.id}>{battle.name}{active?.battle.id === battle.id ? "  (em andamento)" : ""}</option>)}
            </select>
          </div>
          <button className="secondary" onClick={startPicked} disabled={busy || !pick}>▶ Iniciar esta</button>
        </div>
        {allowed.length > 0 && <p style={{ color: "#9a9ac0", fontSize: 12, marginTop: 6 }}>Esta batalha aceita só {allowed.length} presente(s).</p>}
        {session && <div className="row" style={{ marginTop: 10 }}>
          <span className="pill">Lado A: {Math.round(session.side_a_xp).toLocaleString("pt-BR")}</span>
          <span className="pill">Lado B: {Math.round(session.side_b_xp).toLocaleString("pt-BR")}</span>
          <span className="pill">Status: {session.status}</span>
          <a href={`#/arena?battle=${active?.battle.id}`} target="_blank" rel="noreferrer"><button className="secondary">Abrir arena ativa</button></a>
        </div>}
      </div>

      <div className="card">
        <h3>Pessoas do simulador</h3>
        <p style={{ color: "#9a9ac0", fontSize: 13 }}>Cadastre fotos reais de teste. As marcadas são sorteadas quando novos espectadores entram.</p>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}><label>Nome</label><input value={profileName} onChange={(event) => setProfileName(event.target.value)} placeholder="Ex.: Ana" /></div>
          <div style={{ flex: 1 }}><label>Foto do perfil</label><input type="file" accept="image/*" onChange={(event) => setProfileFile(event.target.files?.[0] || null)} /></div>
          <button onClick={addProfile} disabled={busy}>Cadastrar foto</button>
        </div>
        {profileNote && (
          <p
            style={{
              margin: "10px 0 0",
              fontSize: 13,
              color: profileNote.bad ? "#ff8080" : "#4ade80",
            }}
          >
            {profileNote.bad ? "⚠️ " : "✅ "}
            {profileNote.text}
          </p>
        )}
        {profiles.length > 0 && <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 14 }}>
          {profiles.map((profile) => <div key={profile.id} style={{ display: "flex", alignItems: "center", gap: 6, padding: 6, border: "1px solid #343450", borderRadius: 8 }}>
            <input type="checkbox" checked={selectedProfiles.includes(profile.id)} onChange={() => toggleProfile(profile.id)} title={`Usar ${profile.name}`} />
            <img src={assetUrl(profile.avatar_url)} alt={profile.name} style={{ width: 34, height: 34, borderRadius: "50%", objectFit: "cover" }} />
            <span style={{ fontSize: 13 }}>{profile.name}</span>
            <button className="secondary" onClick={() => removeProfile(profile)} disabled={busy}>×</button>
          </div>)}
        </div>}
      </div>

      <div className="card">
        <h3>Simulação contínua</h3>
        <p style={{ color: "#9a9ac0", fontSize: 13 }}>
          Cada pessoa selecionada entra uma única vez e fica sempre no mesmo lado. Se as vagas
          pedidas forem maiores que os perfis disponíveis, o simulador para de preencher quando
          acabarem — ele nunca repete alguém no time normal ou no adversário.
        </p>
        <div className="row" style={{ alignItems: "flex-end", marginBottom: 12 }}>
          <div>
            <label>Máximo no lado A</label>
            <input
              type="number"
              min={0}
              max={500}
              value={teamACount}
              disabled={autoRunning}
              onChange={(event) => setTeamACount(Math.max(0, Math.min(500, Number(event.target.value))))}
              style={{ width: 120 }}
            />
          </div>
          <div>
            <label>Máximo no lado B</label>
            <input
              type="number"
              min={0}
              max={500}
              value={teamBCount}
              disabled={autoRunning}
              onChange={(event) => setTeamBCount(Math.max(0, Math.min(500, Number(event.target.value))))}
              style={{ width: 120 }}
            />
          </div>
          <span style={{ color: "#9a9ac0", fontSize: 12, paddingBottom: 8 }}>
            {selectedProfiles.length} perfil(is) selecionado(s) para {teamACount + teamBCount} vaga(s)
          </span>
        </div>
        {teamACount + teamBCount > selectedProfiles.length && (
          <p style={{ color: "#fbbf24", fontSize: 12, marginTop: 0 }}>
            Há menos pessoas que vagas. Serão usados só os {selectedProfiles.length} perfis selecionados, sem repetir ninguém.
          </p>
        )}
        <div className="row" style={{ alignItems: "center" }}>
          {autoRunning
            ? <button className="secondary" onClick={stopAuto} disabled={busy || !session}>⏸ Parar simulação</button>
            : <button onClick={startAuto} disabled={busy || !pick || selectedProfiles.length === 0 || teamACount + teamBCount === 0}>▶ Iniciar simulação realista</button>}
          <span className="pill" style={{ color: autoRunning ? "#86efac" : undefined }}>{autoRunning ? "ATIVA" : "PAUSADA"}</span>
          {autoRunning && autoStatus?.team_a_joined !== undefined && (
            <>
              <span className="pill">A: {autoStatus.team_a_joined}/{autoStatus.team_a_limit}</span>
              <span className="pill">B: {autoStatus.team_b_joined}/{autoStatus.team_b_limit}</span>
              <span className="pill">Aguardando entrada: {autoStatus.pending ?? 0}</span>
            </>
          )}
          {autoRunning && autoStatus?.profiles_exhausted && <span style={{ color: "#fbbf24", fontSize: 12 }}>Perfis esgotados; nenhum novo usuário será criado.</span>}
        </div>
      </div>

      <div className="card">
        <h3>Fundo completo da arena</h3>
        <p style={{ color: "#9a9ac0", fontSize: 13 }}>A imagem ocupa todo o canvas 1080×1920 atrás dos tanques, avatares e placar. Ao salvar, a arena já aberta recebe a troca.</p>
        <div className="row" style={{ alignItems: "center" }}>
          <input type="file" accept="image/*" onChange={(event) => event.target.files?.[0] && uploadArenaBackground(event.target.files[0])} disabled={busy || !pick} />
          {arenaBackground && <button className="secondary" onClick={clearArenaBackground} disabled={busy}>Remover fundo</button>}
        </div>
        {arenaBackground && <img src={assetUrl(arenaBackground)} alt="Prévia do fundo da arena" style={{ width: 180, maxHeight: 220, objectFit: "cover", marginTop: 10, borderRadius: 6 }} />}
      </div>

      <div className="card">
        <h3>Simular presente</h3>
        <p style={{ color: "#9a9ac0", fontSize: 13 }}>
          Curtida e follow valem para quem já entrou na batalha. O follow só triplica a vida uma vez por pessoa.
        </p>
        <div className="form-grid">
          <div>
            <label>Usuário</label><input value={username} onChange={(event) => setUsername(event.target.value)} />
            <label>Avatar (URL, opcional)</label><input value={avatarUrl} onChange={(event) => setAvatarUrl(event.target.value)} placeholder="https://i.pravatar.cc/150?u=carlos" />
          </div>
          <div>
            <label>Presente</label>
            <select value={giftKey} onChange={(event) => setGiftKey(event.target.value)}>
              {gifts.map((gift) => <option key={gift.id} value={gift.gift_key}>{gift.icon} {gift.name}{!allowed.length || allowed.includes(gift.gift_key) ? "" : " — não vale nesta batalha"}</option>)}
            </select>
            <label>Quantidade</label><input type="number" min={1} value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} />
          </div>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button onClick={simulateGift} disabled={busy || !pick || !giftKey}>SIMULAR PRESENTE</button>
          <button className="secondary" onClick={simulateJoin} disabled={busy || !pick}>Simular novo espectador</button>
          <button className="secondary" onClick={simulateLike} disabled={busy || !pick}>Simular coração/curtida</button>
          <button className="secondary" onClick={simulateFollow} disabled={busy || !pick}>Simular follow (3× vida)</button>
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
        <p style={{ color: "#9a9ac0", fontSize: 13 }}>
          Cada um entra, escolhe um lado e ataca o chefão rival com presentes sorteados.
          Ninguém entra duas vezes: quem já está em campo é pulado, e só volta quem foi
          eliminado.
        </p>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div>
            <label>Ataques por pessoa</label>
            <input
              type="number"
              min={0}
              max={20}
              value={attacksEach}
              onChange={(e) => setAttacksEach(Math.max(0, Math.min(20, Number(e.target.value))))}
              style={{ width: 90 }}
            />
          </div>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          {[100, 250, 500, 1000].map((count) => <button key={count} className="secondary" onClick={() => simulateStress(count)} disabled={busy || !pick}>{count} usuários</button>)}
        </div>
        <div className="row" style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid #262638" }}>
          <button onClick={resetArena} disabled={busy || !pick}>🧹 Limpar arena e reiniciar</button>
          <span style={{ color: "#9a9ac0", fontSize: 12 }}>
            Tira todos os perfis do jogo, devolve a vida dos chefões e para a simulação contínua.
          </span>
        </div>
      </div>

      <div className="card">
        <h3>Log</h3>
        {log.map((line, index) => <div key={index} style={{ fontSize: 13, color: "#b6b6d0" }}>{line}</div>)}
      </div>
    </div>
  );
}
