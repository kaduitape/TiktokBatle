import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";

interface Battle {
  id: string;
  name: string;
}

interface Session {
  id: string;
}

interface Gift {
  id: string;
  gift_key: string;
  tiktok_gift_id: string | null;
  name: string;
  icon: string;
  action_type: "shot" | "missile" | "heal" | "super_heal" | "special";
  value: number;
  target_side: "A" | "B";
  coins: number;
  animation_key: string;
  sound_key: string;
  combo_allowed: boolean;
  multiplier: number;
  active: boolean;
}

interface TikTokObservation {
  tiktok_gift_id: string;
  name: string;
  coins: number | null;
  seen_count: number;
  last_seen_at: string;
  configured_gift_id: string | null;
  configured_gift_key: string | null;
}

interface LiveStatus {
  connected: boolean;
  state: "connecting" | "connected" | "reconnecting" | "error" | "disconnected";
  username: string | null;
  last_error: string | null;
  reconnect_attempt: number;
  events_received: number;
  last_event_at: number | null;
}

interface Diagnostics {
  tiktoklive_installed: boolean;
  tiktoklive_version: string | null;
  public_url: string;
  reconnect_seconds: number;
}

const disconnected: LiveStatus = {
  connected: false,
  state: "disconnected",
  username: null,
  last_error: null,
  reconnect_attempt: 0,
  events_received: 0,
  last_event_at: null,
};

function statusText(status: LiveStatus): string {
  if (status.state === "connected") return "Conectado e recebendo eventos";
  if (status.state === "connecting") return "Conectando ao TikTok...";
  if (status.state === "reconnecting") return `Reconectando (tentativa ${status.reconnect_attempt})...`;
  if (status.state === "error") return "Falha ao conectar";
  return "Desconectado";
}

export default function Live() {
  const [battles, setBattles] = useState<Battle[]>([]);
  const [gifts, setGifts] = useState<Gift[]>([]);
  const [observations, setObservations] = useState<TikTokObservation[]>([]);
  const [battleId, setBattleId] = useState("");
  const [session, setSession] = useState<Session | null>(null);
  const [username, setUsername] = useState("");
  const [status, setStatus] = useState<LiveStatus>(disconnected);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [mappingChoice, setMappingChoice] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadStatic = async () => {
    const [loadedBattles, loadedGifts, loadedDiagnostics] = await Promise.all([
      api.get<Battle[]>("/api/battles"),
      api.get<Gift[]>("/api/gifts"),
      api.get<Diagnostics>("/api/live/diagnostics"),
    ]);
    setBattles(loadedBattles);
    setGifts(loadedGifts);
    setDiagnostics(loadedDiagnostics);
    if (!battleId && loadedBattles[0]) setBattleId(loadedBattles[0].id);
  };

  useEffect(() => {
    loadStatic().catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!battleId) return;
    setSession(null);
    setStatus(disconnected);
    api.post<Session>(`/api/battles/${battleId}/start`)
      .then(setSession)
      .catch((e) => setError(String(e)));
  }, [battleId]);

  const refreshLive = async () => {
    try {
      const observationRequest = api.get<TikTokObservation[]>("/api/gifts/tiktok-observations");
      const statusRequest = session
        ? api.get<LiveStatus>(`/api/live/${session.id}/status`)
        : Promise.resolve(disconnected);
      const [nextStatus, nextObservations] = await Promise.all([statusRequest, observationRequest]);
      setStatus(nextStatus);
      setObservations(nextObservations);
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    refreshLive();
    const id = window.setInterval(refreshLive, 5000);
    return () => window.clearInterval(id);
  }, [session]);

  const publicBase = (diagnostics?.public_url || window.location.origin).replace(/\/$/, "");
  const arenaUrl = battleId ? `${publicBase}/#/arena?battle=${battleId}` : "";
  const unmapped = useMemo(
    () => observations.filter((observation) => !observation.configured_gift_id),
    [observations],
  );

  const copy = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setMessage(`${label} copiada.`);
    } catch {
      setError("Não foi possível copiar automaticamente. Selecione e copie o endereço manualmente.");
    }
  };

  const connect = async () => {
    if (!session || !username.trim()) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.post(`/api/live/${session.id}/connect`, { tiktok_username: username.trim().replace(/^@/, "") });
      setMessage("Solicitação enviada. Aguarde o status mudar para conectado.");
      window.setTimeout(refreshLive, 1000);
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
      setMessage("TikTok LIVE desconectado.");
      window.setTimeout(refreshLive, 250);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const mapGift = async (observation: TikTokObservation) => {
    const giftId = mappingChoice[observation.tiktok_gift_id];
    const gift = gifts.find((candidate) => candidate.id === giftId);
    if (!gift) return;
    setBusy(true);
    setError(null);
    try {
      await api.put(`/api/gifts/${gift.id}`, {
        ...gift,
        tiktok_gift_id: observation.tiktok_gift_id,
        coins: observation.coins ?? gift.coins,
      });
      setMessage(`${observation.name} foi associado a ${gift.name}.`);
      await loadStatic();
      await refreshLive();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h1>Assistente para colocar ao vivo</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Siga as etapas na ordem. A arena fica hospedada na VPS; o OBS/TikTok Live Studio continua sendo responsável por transmitir seu vídeo ao TikTok.
      </p>

      {message && <p className="live-message success">{message}</p>}
      {error && <p className="live-message error">{error}</p>}

      <section className="card live-step">
        <span className="step-number">1</span>
        <div>
          <h3>Servidor e endereço público</h3>
          <p>
            Arena configurada: <code>{publicBase}</code>. O TikTokLive está {diagnostics?.tiktoklive_installed ? "instalado" : "ausente"}
            {diagnostics?.tiktoklive_version ? ` (v${diagnostics.tiktoklive_version})` : ""}.
          </p>
          {!diagnostics?.tiktoklive_installed && (
            <p className="error-text">Faça o deploy novamente com Docker antes de continuar: a imagem do backend não possui TikTokLive.</p>
          )}
          <p className="hint">O Traefik deve servir este endereço em HTTPS. A VPS não deve expor PostgreSQL, Redis ou a porta do backend.</p>
        </div>
      </section>

      <section className="card live-step">
        <span className="step-number">2</span>
        <div className="live-step-content">
          <h3>Escolha a batalha e abra a fonte OBS</h3>
          <label>Batalha que receberá os eventos</label>
          <select value={battleId} onChange={(event) => setBattleId(event.target.value)}>
            {battles.map((battle) => <option key={battle.id} value={battle.id}>{battle.name}</option>)}
          </select>
          {session && <p className="hint">Sessão pronta: <code>{session.id}</code></p>}
          <label>URL da Fonte de navegador do OBS (1080 x 1920)</label>
          <div className="row">
            <input className="live-url" readOnly value={arenaUrl} />
            <button className="secondary" onClick={() => copy(arenaUrl, "URL da arena")}>Copiar</button>
            <a className="button-link" href={arenaUrl} target="_blank" rel="noreferrer">Abrir arena</a>
          </div>
          <p className="hint">No OBS: Fontes → + → Navegador → cole a URL → largura 1080, altura 1920. Mantenha a fonte aberta durante a LIVE.</p>
        </div>
      </section>

      <section className="card live-step">
        <span className="step-number">3</span>
        <div className="live-step-content">
          <h3>Conecte a LIVE real</h3>
          <p>Inicie a LIVE no TikTok primeiro. Depois informe o usuário do criador, sem <code>@</code>.</p>
          <div className="row">
            <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="seuusuario" />
            {status.state === "connected" || status.state === "connecting" || status.state === "reconnecting" ? (
              <button className="secondary" onClick={disconnect} disabled={busy}>Desconectar</button>
            ) : (
              <button onClick={connect} disabled={busy || !session || !username.trim() || !diagnostics?.tiktoklive_installed}>Conectar TikTok</button>
            )}
            <button className="secondary" onClick={refreshLive} disabled={busy}>Atualizar status</button>
          </div>
          <p className={`live-status ${status.state}`}><strong>{statusText(status)}</strong>{status.username ? ` @${status.username}` : ""}</p>
          <p className="hint">Eventos recebidos nesta sessão: {status.events_received}. {status.last_error && `Detalhe: ${status.last_error}`}</p>
        </div>
      </section>

      <section className="card live-step">
        <span className="step-number">4</span>
        <div className="live-step-content">
          <h3>Associe os presentes reais às ações</h3>
          <p>Envie um presente de teste. Ele aparece aqui com o ID exato do TikTok; associe-o a uma regra do jogo. Presentes sem associação são registrados, mas não causam dano/cura.</p>
          {!observations.length && <p className="hint">Nenhum presente real foi recebido ainda. Conecte a LIVE e envie um presente de teste.</p>}
          {observations.map((observation) => (
            <div className="gift-observation" key={observation.tiktok_gift_id}>
              <div>
                <strong>{observation.name}</strong> <code>{observation.tiktok_gift_id}</code>
                <small>{observation.coins ?? "?"} moedas · visto {observation.seen_count}x</small>
              </div>
              {observation.configured_gift_id ? (
                <span className="pill mapped">Mapeado: {observation.configured_gift_key}</span>
              ) : (
                <div className="row">
                  <select
                    value={mappingChoice[observation.tiktok_gift_id] || ""}
                    onChange={(event) => setMappingChoice({ ...mappingChoice, [observation.tiktok_gift_id]: event.target.value })}
                  >
                    <option value="">Escolha a ação do jogo</option>
                    {gifts.map((gift) => <option key={gift.id} value={gift.id}>{gift.icon} {gift.name} ({gift.gift_key})</option>)}
                  </select>
                  <button onClick={() => mapGift(observation)} disabled={busy || !mappingChoice[observation.tiktok_gift_id]}>Associar</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="card live-step">
        <span className="step-number">5</span>
        <div>
          <h3>Checklist antes de abrir para o público</h3>
          <ul className="checklist">
            <li className={diagnostics?.tiktoklive_installed ? "done" : ""}>Backend com TikTokLive instalado</li>
            <li className={!!session ? "done" : ""}>Batalha e sessão da arena prontas</li>
            <li className={status.state === "connected" ? "done" : ""}>LIVE conectada</li>
            <li className={!unmapped.length && observations.length ? "done" : ""}>Presentes recebidos estão mapeados ({unmapped.length} pendente{unmapped.length === 1 ? "" : "s"})</li>
            <li>Fonte de navegador aberta no OBS em 1080 x 1920</li>
          </ul>
          <p className="hint">Se a conexão cair, o backend tenta reconectar a cada {diagnostics?.reconnect_seconds ?? 10}s, aumentando o intervalo até um minuto. Para encerrar, use Desconectar.</p>
        </div>
      </section>
    </div>
  );
}
