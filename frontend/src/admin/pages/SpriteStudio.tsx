import { useEffect, useState } from "react";
import { API_BASE, api } from "../../api/client";

interface Status {
  configured: boolean;
  /** "panel" = colada aqui, "env" = variável do servidor, null = nenhuma. */
  source: "panel" | "env" | null;
  masked: string | null;
  model: string;
  max_poses: number;
}

interface Sheet {
  url: string | null;
  columns: number;
  rows: number;
  frame_count: number;
  frame_width: number;
  frame_height: number;
  hit_url: string | null;
  fire_url: string | null;
}

interface Character {
  id: string;
  name: string;
  [key: string]: unknown;
}

// A walk-cycle-ish loop that works for almost any caricature, so the page is
// useful before the admin writes a single pose of their own.
/** Transparent-background preview backdrop. */
const CHECKER = "repeating-conic-gradient(#2a2a3a 0% 25%, #1b1b28 0% 50%) 50% / 24px 24px";

const DEFAULT_POSES = [
  "braços abaixados ao lado do corpo, boca fechada, expressão neutra",
  "braço direito a meio caminho, subindo, boca levemente aberta",
  "braço direito levantado na altura do ombro, boca aberta falando",
  "braço direito a meio caminho, descendo, boca levemente aberta",
];

/** Ready-made loops. Each one is written so the last pose flows back into the
 * first, which is what keeps the animation from jumping when it repeats. */
const POSE_PRESETS: { label: string; poses: string[] }[] = [
  {
    label: "🕺 Dançando",
    poses: [
      "de pé, peso no pé esquerdo, quadril inclinado para a esquerda, os dois braços dobrados na altura do peito, sorrindo",
      "saltando levemente, os dois braços levantados acima da cabeça, corpo esticado, sorrindo de boca aberta",
      "de pé, peso no pé direito, quadril inclinado para a direita, os dois braços dobrados na altura do peito, sorrindo",
      "agachado de leve, joelhos dobrados, braços abertos para os lados na altura da cintura, sorrindo de boca aberta",
    ],
  },
  {
    label: "🗣️ Falando",
    poses: DEFAULT_POSES,
  },
  {
    label: "🎉 Comemorando",
    poses: [
      "os dois punhos fechados erguidos acima da cabeça, boca aberta gritando de alegria",
      "punhos na altura do peito, joelhos dobrados como quem vai pular, sorrindo",
      "no ar em um pulo curto, pernas dobradas para trás, braços abertos, boca bem aberta",
      "aterrissando com os joelhos dobrados, braços descendo pelos lados, sorrindo",
    ],
  },
  {
    label: "😤 Provocando",
    poses: [
      "braços cruzados no peito, sobrancelha levantada, sorriso de canto",
      "uma das mãos apontando para a frente, corpo inclinado à frente, boca aberta provocando",
      "as duas mãos abertas ao lado da cabeça fazendo pouco caso, língua de fora",
      "braços cruzados no peito de novo, sobrancelha levantada, sorriso de canto",
    ],
  },
];

export default function SpriteStudio() {
  const [status, setStatus] = useState<Status | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [description, setDescription] = useState("");
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [wantHit, setWantHit] = useState(true);
  const [wantFire, setWantFire] = useState(true);
  const [poses, setPoses] = useState<string[]>(DEFAULT_POSES);
  const [columns, setColumns] = useState(0);
  const [fps, setFps] = useState(8);
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [targetId, setTargetId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [applied, setApplied] = useState("");
  const [keyInput, setKeyInput] = useState("");
  const [keyBusy, setKeyBusy] = useState(false);
  const [keyMsg, setKeyMsg] = useState("");
  const [keyErr, setKeyErr] = useState("");

  useEffect(() => {
    api.get<Status>("/api/sprites/status").then(setStatus).catch(() => setStatus(null));
    api.get<Character[]>("/api/characters").then(setCharacters);
  }, []);

  /** Runs a key action and folds the outcome into the banner. The key itself
   * is dropped from the form as soon as it is sent. */
  const keyAction = async (run: () => Promise<unknown>, ok: string) => {
    setKeyBusy(true);
    setKeyMsg("");
    setKeyErr("");
    try {
      await run();
      setStatus(await api.get<Status>("/api/sprites/status"));
      setKeyMsg(ok);
    } catch (err) {
      setKeyErr(err instanceof Error ? err.message : String(err));
    } finally {
      setKeyBusy(false);
    }
  };

  const saveKey = () =>
    keyAction(async () => {
      await api.put("/api/sprites/key", { key: keyInput.trim() });
      setKeyInput("");
    }, "Chave salva.");

  const testKey = () =>
    keyAction(async () => {
      const body = keyInput.trim() ? { key: keyInput.trim() } : undefined;
      const res = await api.post<{ message: string }>("/api/sprites/key/test", body);
      setKeyMsg(res.message);
    }, "Chave aceita pela API.");

  const removeKey = () =>
    keyAction(async () => {
      await api.del("/api/sprites/key");
      setKeyInput("");
    }, "Chave removida.");

  const uploadBase = async (file: File) => {
    setBusy(true);
    setError("");
    try {
      const { url } = await api.upload("/api/characters/upload", file);
      setBaseUrl(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const setPose = (index: number, value: string) =>
    setPoses((list) => list.map((p, i) => (i === index ? value : p)));

  const addPose = () => setPoses((list) => [...list, ""]);
  const removePose = (index: number) => setPoses((list) => list.filter((_, i) => i !== index));

  const generate = async () => {
    setBusy(true);
    setError("");
    setApplied("");
    setSheet(null);
    try {
      const result = await api.post<Sheet>("/api/sprites/generate", {
        description,
        poses: poses.filter((p) => p.trim()),
        base_image_url: baseUrl,
        want_hit: wantHit,
        want_fire: wantFire,
        columns,
      });
      setSheet(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const applyToCharacter = async () => {
    if (!sheet || !targetId) return;
    setBusy(true);
    setError("");
    try {
      const character = await api.get<Character>(`/api/characters/${targetId}`);
      const { id, ...rest } = character;
      await api.put(`/api/characters/${id}`, {
        ...rest,
        // Only overwrite what this run actually produced.
        ...(sheet.url
          ? {
              image_url: sheet.url,
              sprite_columns: sheet.columns,
              sprite_rows: sheet.rows,
              sprite_frame_count: sheet.frame_count,
              sprite_fps: fps,
            }
          : {}),
        ...(sheet.hit_url ? { hit_image_url: sheet.hit_url } : {}),
        ...(sheet.fire_url ? { fire_image_url: sheet.fire_url } : {}),
      });
      const parts = [
        sheet.url && "animação",
        sheet.hit_url && "dano",
        sheet.fire_url && "disparo",
      ].filter(Boolean);
      setApplied(`Aplicado em ${character.name} (${parts.join(", ")}). Recarregue a Arena para ver.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const usablePoses = poses.filter((p) => p.trim()).length;

  return (
    <div>
      <h1>Gerar sprites</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Descreva o personagem uma vez e liste as poses. A primeira pose é gerada do
        zero e as outras são <b>edições da mesma imagem</b> — é isso que mantém o
        personagem igual de um quadro para o outro. No fim sai a folha montada,
        pronta para virar animação.
      </p>

      <div
        className="card"
        style={{ borderLeft: `4px solid ${status?.configured ? "#4ade80" : "#e0a01b"}` }}
      >
        <h3>Chave da API de imagem</h3>
        {status?.configured ? (
          <p style={{ fontSize: 13 }}>
            Configurada ({status.masked}) —{" "}
            {status.source === "panel" ? "colada aqui no painel" : "vinda do .env do servidor"}.
          </p>
        ) : (
          <p style={{ fontSize: 13, lineHeight: 1.6 }}>
            Pegue uma chave em <code>platform.openai.com</code> e cole abaixo. Sem ela o
            resto do sistema funciona normalmente — só esta página fica desligada, e você
            ainda pode montar folhas à mão com <code>scripts/make_spritesheet.py</code>.
          </p>
        )}

        <label>{status?.configured ? "Substituir por outra chave" : "Cole a chave aqui"}</label>
        <input
          type="password"
          autoComplete="off"
          placeholder="sk-..."
          value={keyInput}
          onChange={(e) => setKeyInput(e.target.value)}
          style={{ width: "100%", fontFamily: "monospace" }}
        />
        <div className="row" style={{ marginTop: 10 }}>
          <button onClick={saveKey} disabled={keyBusy || keyInput.trim().length < 8}>
            Salvar chave
          </button>
          <button
            className="secondary"
            onClick={testKey}
            disabled={keyBusy || (!status?.configured && keyInput.trim().length < 8)}
          >
            Testar
          </button>
          {status?.source === "panel" && (
            <button className="secondary" onClick={removeKey} disabled={keyBusy}>
              Remover chave salva
            </button>
          )}
        </div>
        {keyMsg && <p style={{ color: "#4ade80", fontSize: 13, marginTop: 10 }}>{keyMsg}</p>}
        {keyErr && (
          <p style={{ color: "#ff6b6b", fontSize: 13, marginTop: 10, whiteSpace: "pre-wrap" }}>{keyErr}</p>
        )}
        <p style={{ color: "#9a9ac0", fontSize: 12, marginTop: 10, lineHeight: 1.6 }}>
          A chave é guardada no banco de dados deste servidor e nunca volta para o
          navegador — o painel só mostra os quatro últimos caracteres. Como o sistema não
          tem cofre de senhas, um backup do banco carrega a chave junto: se o servidor for
          compartilhado, prefira a variável <code>BATTLE_IMAGE_API_KEY</code> no{" "}
          <code>.env</code>. Uma chave colada aqui tem prioridade sobre a do <code>.env</code>.
        </p>
      </div>

      <div className="card">
        <h3>Personagem</h3>

        <label>Caricatura pronta (opcional)</label>
        <p style={{ color: "#9a9ac0", fontSize: 12, margin: "2px 0 8px" }}>
          Se você já tem o desenho, suba aqui: ele vira o <b>quadro 1</b> e serve de
          referência para todas as outras imagens, então a semelhança é a do seu
          desenho e não a que o modelo inventar. Sem imagem, o primeiro quadro é
          gerado a partir da descrição abaixo.
        </p>
        <input type="file" accept="image/*" onChange={(e) => e.target.files && uploadBase(e.target.files[0])} />
        {baseUrl && (
          <div className="row" style={{ marginTop: 6 }}>
            <img
              src={`${API_BASE}${baseUrl}`}
              alt="Imagem base"
              style={{ width: 64, height: 64, objectFit: "contain" }}
            />
            <span className="pill">quadro 1</span>
            <button className="secondary" onClick={() => setBaseUrl(null)}>Remover</button>
          </div>
        )}

        <label style={{ marginTop: 14 }}>
          Descrição {baseUrl ? "(ajuda o modelo a entender o desenho)" : "(vale para todas as poses)"}
        </label>
        <textarea
          rows={3}
          placeholder="Ex: caricatura cartoon de um homem barbudo de terno azul e gravata vermelha"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          style={{ width: "100%" }}
        />

        <label style={{ marginTop: 14 }}>
          Poses ({usablePoses}
          {status ? ` de no máximo ${status.max_poses}` : ""})
        </label>
        <p style={{ color: "#9a9ac0", fontSize: 12, margin: "2px 0 8px" }}>
          A animação roda em loop, então a última pose tem que combinar com a primeira.
        </p>
        <div className="gift-filters" style={{ marginBottom: 10 }}>
          <span style={{ color: "#9a9ac0", fontSize: 12 }}>Começar de um pronto:</span>
          {POSE_PRESETS.map((preset) => (
            <button
              key={preset.label}
              className="chip"
              onClick={() => setPoses([...preset.poses])}
              title="Substitui as poses abaixo"
            >
              {preset.label}
            </button>
          ))}
        </div>
        {poses.map((pose, i) => (
          <div className="row" key={i} style={{ marginBottom: 6 }}>
            <span className="pill">{i + 1}</span>
            <input
              style={{ flex: 1 }}
              value={pose}
              placeholder="descreva só o que muda nesta pose"
              onChange={(e) => setPose(i, e.target.value)}
            />
            <button className="secondary" onClick={() => removePose(i)} disabled={poses.length <= 1}>
              Remover
            </button>
          </div>
        ))}
        <button
          className="secondary"
          onClick={addPose}
          disabled={!!status && poses.length >= status.max_poses}
        >
          + Adicionar pose
        </button>

        <label style={{ marginTop: 14 }}>Imagens de ação</label>
        <p style={{ color: "#9a9ac0", fontSize: 12, margin: "2px 0 8px" }}>
          Desenhos avulsos que entram por um instante quando a ação acontece no jogo.
          Cada um é uma imagem cobrada à parte.
        </p>
        <label>
          <input type="checkbox" checked={wantHit} onChange={(e) => setWantHit(e.target.checked)} /> Ao
          levar dano — encolhendo, cara de dor
        </label>
        <label>
          <input type="checkbox" checked={wantFire} onChange={(e) => setWantFire(e.target.checked)} /> Ao
          atacar — jogando a bomba, braço esticado (Guerra de Tanques)
        </label>
        <p style={{ color: "#9a9ac0", fontSize: 12, margin: "6px 0 0" }}>
          As duas entram sozinhas no jogo: a de dano quando o personagem leva um golpe, a de
          ataque quando ele joga a bomba. Passado o instante, a dança volta a rodar.
        </p>

        <div className="row" style={{ marginTop: 14 }}>
          <div>
            <label>Colunas na folha (0 = tudo numa linha)</label>
            <input type="number" min={0} value={columns} onChange={(e) => setColumns(Number(e.target.value))} />
          </div>
          <div>
            <label>Quadros por segundo</label>
            <input type="number" min={1} value={fps} onChange={(e) => setFps(Number(e.target.value))} />
          </div>
        </div>

        <div className="row" style={{ marginTop: 14 }}>
          <button
            onClick={generate}
            disabled={
              busy ||
              (!description.trim() && !baseUrl) ||
              (usablePoses === 0 && !wantHit && !wantFire)
            }
          >
            {busy ? "Gerando…" : "Gerar folha"}
          </button>
          {busy && (
            <span style={{ color: "#9a9ac0", fontSize: 13 }}>
              Cada pose é uma chamada à API — com 4 poses costuma levar 1 a 2 minutos.
            </span>
          )}
        </div>

        {error && (
          <p style={{ color: "#ff6b6b", fontSize: 13, marginTop: 12, whiteSpace: "pre-wrap" }}>{error}</p>
        )}
      </div>

      {sheet && (
        <div className="card">
          <h3>Resultado</h3>
          {sheet.url && (
            <>
              <img
                src={`${API_BASE}${sheet.url}`}
                alt="folha de sprites gerada"
                style={{ maxWidth: "100%", background: CHECKER, borderRadius: 6 }}
              />
              <p style={{ fontSize: 13, marginTop: 10 }}>
                {sheet.columns} coluna(s) × {sheet.rows} linha(s) — {sheet.frame_count} quadros de{" "}
                {sheet.frame_width}×{sheet.frame_height} px
              </p>
            </>
          )}

          {(sheet.hit_url || sheet.fire_url) && (
            <div className="row" style={{ marginTop: 10, alignItems: "flex-start" }}>
              {sheet.hit_url && (
                <figure style={{ margin: 0 }}>
                  <img
                    src={`${API_BASE}${sheet.hit_url}`}
                    alt="pose de dano"
                    style={{ width: 160, background: CHECKER, borderRadius: 6 }}
                  />
                  <figcaption style={{ fontSize: 12, color: "#9a9ac0" }}>ao levar dano</figcaption>
                </figure>
              )}
              {sheet.fire_url && (
                <figure style={{ margin: 0 }}>
                  <img
                    src={`${API_BASE}${sheet.fire_url}`}
                    alt="pose de disparo"
                    style={{ width: 160, background: CHECKER, borderRadius: 6 }}
                  />
                  <figcaption style={{ fontSize: 12, color: "#9a9ac0" }}>ao disparar</figcaption>
                </figure>
              )}
            </div>
          )}

          <div className="row" style={{ marginTop: 10 }}>
            <select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
              <option value="">Aplicar em qual personagem…</option>
              {characters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <button onClick={applyToCharacter} disabled={busy || !targetId}>
              Aplicar
            </button>
            {sheet.url && (
              <a className="secondary" href={`${API_BASE}${sheet.url}`} target="_blank" rel="noreferrer">
                Baixar PNG
              </a>
            )}
          </div>
          {applied && <p style={{ color: "#4ade80", fontSize: 13, marginTop: 10 }}>{applied}</p>}
        </div>
      )}
    </div>
  );
}
