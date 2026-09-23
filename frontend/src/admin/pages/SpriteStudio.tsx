import { useEffect, useState } from "react";
import { API_BASE, api } from "../../api/client";

/** One image service the panel can draw with. */
interface ProviderInfo {
  id: string;
  label: string;
  default_size: string;
  supports_transparency: boolean;
  configured: boolean;
  source: "panel" | "env" | null;
  masked: string | null;
  model: string;
}

interface Status {
  configured: boolean;
  /** "panel" = colada aqui, "env" = variável do servidor, null = nenhuma. */
  source: "panel" | "env" | null;
  masked: string | null;
  model: string;
  provider: string;
  providers: ProviderInfo[];
  max_poses: number;
  max_gestures: number;
  max_gesture_poses: number;
}

/** One row of the sheet, named, in the shape the game reads it. */
interface Clip {
  name: string;
  row: number;
  frames: number;
  kind?: "idle" | "gesture";
  weight?: number;
  fps?: number;
  lift?: number;
}

/** A short movement the character does between loops of the base one. */
interface Gesture {
  name: string;
  poses: string[];
  lift: number;
  weight: number;
  fps: number;
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
  clips: Clip[];
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

/** The little things a character does when nothing is happening.
 *
 * The base loop alone is a machine: the same frames, forever. These are played
 * once, at uneven intervals, and hand the character straight back to the loop
 * -- which is the difference between a character that is running and one that
 * is alive. Each becomes its own row of the sheet.
 *
 * `lift` is how far off the floor the sprite rises while the clip plays: the
 * sheet stands every frame on its feet, so a jump drawn as art alone never
 * leaves the ground.
 */
const GESTURE_PRESETS: (Gesture & { label: string })[] = [
  {
    label: "👀 Piscada",
    name: "piscada",
    weight: 4,
    fps: 14,
    lift: 0,
    poses: [
      "os olhos estão quase fechados, pálpebras descendo, o resto do corpo igual ao da referência",
      "os olhos estão completamente fechados, pálpebras relaxadas, o resto do corpo igual ao da referência",
    ],
  },
  {
    label: "🦘 Pulinho",
    name: "pulo",
    weight: 2,
    fps: 12,
    lift: 0.18,
    poses: [
      "agachado, joelhos bem dobrados, braços recuados, prestes a saltar",
      "no ar, pernas dobradas e recolhidas para trás, braços esticados para cima, boca aberta de alegria",
      "aterrissando, joelhos dobrados amortecendo, braços descendo pelos lados",
    ],
  },
  {
    label: "😛 Língua de fora",
    name: "lingua",
    weight: 2,
    fps: 10,
    lift: 0,
    poses: [
      "a boca está começando a abrir, os olhos apertados de travessura",
      "a língua está bem de fora, os dois olhos apertados, cabeça levemente inclinada, cara de deboche",
      "a língua está voltando para dentro, a boca quase fechada, um olho ainda apertado",
    ],
  },
  {
    label: "🥊 Pose de luta",
    name: "luta",
    weight: 2,
    fps: 12,
    lift: 0,
    poses: [
      "os dois punhos fechados erguidos na guarda diante do rosto, corpo de lado, joelhos flexionados",
      "o punho da frente sai em um soco curto, o tronco gira acompanhando, o outro punho protege o queixo",
      "o punho volta para a guarda, o peso desloca para a perna de trás, olhar fixo à frente",
    ],
  },
  {
    label: "👋 Aceno",
    name: "aceno",
    weight: 2,
    fps: 10,
    lift: 0,
    poses: [
      "um braço sobe até a altura da cabeça, a mão aberta, sorrindo",
      "a mão aberta inclina para um lado, acenando, sorriso maior",
      "a mão aberta inclina para o outro lado, ainda acenando",
    ],
  },
  {
    label: "💃 Rodopio",
    name: "rodopio",
    weight: 1,
    fps: 12,
    lift: 0.06,
    poses: [
      "o corpo começou a girar, está de três quartos, os braços acompanhando o giro",
      "o corpo está de costas no meio do giro, os braços abertos",
      "o corpo voltou a ficar de frente, os braços descendo, sorrindo",
    ],
  },
];

/** A finished animated character, kept so it can be applied to any character
 * later without generating (and paying for) it again. */
interface SpriteModel {
  id: string;
  name: string;
  image_url: string | null;
  sprite_columns: number;
  sprite_rows: number;
  sprite_frame_count: number;
  sprite_fps: number;
  hit_image_url: string | null;
  fire_image_url: string | null;
  sprite_clips: Clip[];
  description: string | null;
  created_at: string;
}

/** The environment variable each service reads, for the note about keeping a
 * key out of a shared database. */
const ENV_VAR: Record<string, string> = {
  openai: "BATTLE_IMAGE_API_KEY",
  gemini: "BATTLE_GEMINI_API_KEY",
  aisa: "BATTLE_AISA_API_KEY",
};

interface Job {
  job_id: string;
  status: "running" | "done" | "error";
  done: number;
  total: number;
  label: string;
  result: Sheet | null;
  error: string | null;
}

export default function SpriteStudio() {
  const [status, setStatus] = useState<Status | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [description, setDescription] = useState("");
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [progress, setProgress] = useState("");
  const [modelName, setModelName] = useState("");
  const [models, setModels] = useState<SpriteModel[]>([]);
  const [wantHit, setWantHit] = useState(true);
  const [wantFire, setWantFire] = useState(true);
  const [poses, setPoses] = useState<string[]>(DEFAULT_POSES);
  // The three that make the biggest difference for the fewest images.
  const [gestureNames, setGestureNames] = useState<string[]>(["piscada", "pulo", "lingua"]);
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
    api.get<SpriteModel[]>("/api/sprites/models").then(setModels).catch(() => undefined);
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

  const provider = status?.provider ?? "openai";
  const current = status?.providers?.find((entry) => entry.id === provider);

  const saveKey = () =>
    keyAction(async () => {
      await api.put("/api/sprites/key", { key: keyInput.trim(), provider });
      setKeyInput("");
    }, "Chave salva.");

  const testKey = () =>
    keyAction(async () => {
      const res = await api.post<{ message: string }>("/api/sprites/key/test", {
        key: keyInput.trim() || undefined,
        provider,
      });
      setKeyMsg(res.message);
    }, "Chave aceita pela API.");

  const removeKey = () =>
    keyAction(async () => {
      await api.del(`/api/sprites/key?provider=${provider}`);
      setKeyInput("");
    }, "Chave removida.");

  /** Each service keeps its own key, so switching back does not mean pasting
   * the previous one again. */
  const chooseProvider = (id: string) =>
    keyAction(async () => {
      await api.put("/api/sprites/provider", { provider: id });
      setKeyInput("");
    }, "Provedor alterado.");

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

  /** Kept in preset order, so the rows of the sheet always come out the same
   * way round no matter which order they were clicked in. */
  const chosenGestures = GESTURE_PRESETS.filter((g) => gestureNames.includes(g.name));
  const gestureFrames = chosenGestures.reduce((sum, g) => sum + g.poses.length, 0);

  const toggleGesture = (name: string) =>
    setGestureNames((list) =>
      list.includes(name)
        ? list.filter((n) => n !== name)
        : list.length >= (status?.max_gestures ?? 6)
          ? list
          : [...list, name],
    );

  const setPose = (index: number, value: string) =>
    setPoses((list) => list.map((p, i) => (i === index ? value : p)));

  const addPose = () => setPoses((list) => [...list, ""]);
  const removePose = (index: number) => setPoses((list) => list.filter((_, i) => i !== index));

  /** Generation makes one call to the image provider per frame and runs well
   * past a minute. Waiting on a single request meant whatever proxy sits in
   * front of the app killed it first -- Cloudflare answers 504 at 100 seconds
   * -- so the request only starts the job and we ask how it is going. */
  const generate = async () => {
    setBusy(true);
    setError("");
    setApplied("");
    setSheet(null);
    setProgress("começando...");
    try {
      const started = await api.post<Job>("/api/sprites/generate", {
        description,
        poses: poses.filter((p) => p.trim()),
        base_image_url: baseUrl,
        want_hit: wantHit,
        want_fire: wantFire,
        columns,
        gestures: chosenGestures.map(({ label: _label, ...gesture }) => gesture),
      });

      // Generous ceiling: eight frames at ~20s each, plus room to spare.
      const deadline = Date.now() + 10 * 60 * 1000;
      for (;;) {
        await new Promise((r) => setTimeout(r, 2500));
        const job = await api.get<Job>(`/api/sprites/jobs/${started.job_id}`);

        if (job.status === "done" && job.result) {
          setSheet(job.result);
          setProgress("");
          return;
        }
        if (job.status === "error") {
          setError(job.error || "A geração falhou.");
          setProgress("");
          return;
        }
        setProgress(
          job.total
            ? `gerando ${job.done} de ${job.total}${job.label ? ` — ${job.label}` : ""}...`
            : "começando...",
        );
        if (Date.now() > deadline) {
          setError("A geração passou de 10 minutos. Confira o servidor.");
          setProgress("");
          return;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setProgress("");
    } finally {
      setBusy(false);
    }
  };

  const loadModels = () =>
    api.get<SpriteModel[]>("/api/sprites/models").then(setModels).catch(() => undefined);

  const saveModel = async () => {
    if (!sheet || !modelName.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.post("/api/sprites/models", {
        name: modelName.trim(),
        image_url: sheet.url,
        sprite_columns: sheet.columns,
        sprite_rows: sheet.rows,
        sprite_frame_count: sheet.frame_count,
        sprite_fps: fps,
        hit_image_url: sheet.hit_url,
        fire_image_url: sheet.fire_url,
        sprite_clips: sheet.clips,
        description,
        poses: poses.filter((pose) => pose.trim()),
      });
      setApplied(
        `Modelo "${modelName.trim()}" salvo. Em Personagens, use "Criar a partir de modelo".`,
      );
      setModelName("");
      await loadModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const removeModel = async (model: SpriteModel) => {
    if (!window.confirm(`Excluir o modelo "${model.name}"? Os personagens já criados com ele continuam iguais.`)) return;
    setBusy(true);
    try {
      await api.del(`/api/sprites/models/${model.id}`);
      await loadModels();
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
              // Without these the game has no idea which row is which, and
              // plays the whole grid -- gestures included -- as one loop.
              sprite_clips: sheet.clips,
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
        personagem igual de um quadro para o outro. Marque também alguns
        <b> gestos</b>: eles entram sozinhos entre as voltas da animação e são o que
        separa um personagem vivo de um boneco repetindo os mesmos quadros.
      </p>

      <div
        className="card"
        style={{ borderLeft: `4px solid ${status?.configured ? "#4ade80" : "#e0a01b"}` }}
      >
        <h3>Quem desenha</h3>
        <p style={{ color: "#9a9ac0", fontSize: 12, margin: "2px 0 10px" }}>
          Cada serviço guarda a própria chave — trocar de um para o outro e voltar não
          exige colar a chave de novo.
        </p>
        <div className="gift-filters" style={{ marginBottom: 12 }}>
          {(status?.providers ?? []).map((entry) => (
            <button
              key={entry.id}
              className={`chip ${entry.id === provider ? "on" : ""}`}
              onClick={() => chooseProvider(entry.id)}
              disabled={keyBusy || entry.id === provider}
            >
              {entry.configured ? "✅" : "⚠️"} {entry.label}
            </button>
          ))}
        </div>

        {current && !current.supports_transparency && (
          <p style={{ color: "#9a9ac0", fontSize: 12, margin: "0 0 10px" }}>
            Este serviço não tem botão de fundo transparente, então costuma devolver o
            personagem sobre um fundo liso. <strong>O sistema recorta esse fundo sozinho</strong>{" "}
            — o recorte começa pela borda, então branco de dentro do personagem não some.
            Se a arte vier sobre um cenário (não um fundo liso), aí o recorte não é feito e a
            prévia mostra o fundo: nesse caso gere pela OpenAI, que tem o recurso de verdade.
          </p>
        )}

        <h3 style={{ marginTop: 0 }}>Chave de {current?.label ?? "imagem"}</h3>
        {status?.configured ? (
          <p style={{ fontSize: 13 }}>
            Configurada ({status.masked}) —{" "}
            {status.source === "panel" ? "colada aqui no painel" : "vinda do .env do servidor"}.
            Modelo: <code>{status.model}</code>.
          </p>
        ) : (
          <p style={{ fontSize: 13, lineHeight: 1.6 }}>
            Pegue uma chave em{" "}
            <code>
              {provider === "gemini"
                ? "aistudio.google.com"
                : provider === "aisa"
                  ? "aisa.one"
                  : "platform.openai.com"}
            </code>{" "}
            e cole abaixo. Sem ela o resto do sistema funciona normalmente — só esta página
            fica desligada, e você ainda pode montar folhas à mão com{" "}
            <code>scripts/make_spritesheet.py</code>.
          </p>
        )}

        <label>{status?.configured ? "Substituir por outra chave" : "Cole a chave aqui"}</label>
        <input
          type="password"
          autoComplete="off"
          placeholder={provider === "gemini" ? "AIza..." : "sk-..."}
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
          compartilhado, prefira a variável <code>{ENV_VAR[provider] ?? "BATTLE_IMAGE_API_KEY"}</code> no{" "}
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

        <label style={{ marginTop: 18 }}>
          Gestos ({chosenGestures.length}
          {status ? ` de no máximo ${status.max_gestures}` : ""})
        </label>
        <p style={{ color: "#9a9ac0", fontSize: 12, margin: "2px 0 8px", lineHeight: 1.6 }}>
          O movimento base sozinho repete os mesmos quadros para sempre, e é isso que
          faz o personagem parecer um robô. Cada gesto vira uma <b>linha própria</b> da
          folha e o jogo o encaixa entre as voltas do movimento base, em intervalos
          irregulares — uma piscada aqui, um pulinho ali. Cada quadro de gesto é uma
          imagem cobrada à parte.
        </p>
        <div className="gift-filters" style={{ marginBottom: 8 }}>
          {GESTURE_PRESETS.map((preset) => (
            <button
              key={preset.name}
              className={`chip ${gestureNames.includes(preset.name) ? "on" : ""}`}
              onClick={() => toggleGesture(preset.name)}
              title={preset.poses.join(" → ")}
            >
              {preset.label} · {preset.poses.length}q
            </button>
          ))}
        </div>
        <p style={{ color: "#9a9ac0", fontSize: 12, margin: 0 }}>
          {gestureFrames > 0
            ? `${gestureFrames} quadro(s) de gesto além das ${usablePoses} pose(s) do movimento base.`
            : "Sem gestos o personagem só repete o movimento base."}
        </p>

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
            <input
              type="number"
              min={0}
              value={columns}
              disabled={chosenGestures.length > 0}
              onChange={(e) => setColumns(Number(e.target.value))}
            />
            {chosenGestures.length > 0 && (
              <p style={{ color: "#9a9ac0", fontSize: 12, margin: "4px 0 0", maxWidth: 260 }}>
                Com gestos a folha é montada uma linha por movimento — é assim que o jogo
                sabe onde cada um começa.
              </p>
            )}
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
              {progress || "começando..."} — cada pose é uma chamada à API, com 4 poses costuma
              levar 1 a 2 minutos. Pode deixar esta aba aberta.
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
              {sheet.clips.length > 0 && (
                <ul style={{ color: "#9a9ac0", fontSize: 12, margin: "0 0 4px", paddingLeft: 18 }}>
                  {sheet.clips.map((clip) => (
                    <li key={clip.row}>
                      linha {clip.row + 1}: <b>{clip.name}</b> — {clip.frames} quadro(s),{" "}
                      {clip.kind === "gesture" ? "tocado de vez em quando" : "em loop"}
                      {clip.lift ? `, sai do chão` : ""}
                    </li>
                  ))}
                </ul>
              )}
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

          <div
            className="row"
            style={{ marginTop: 14, alignItems: "flex-end", paddingTop: 12, borderTop: "1px solid #262638" }}
          >
            <div style={{ flex: 1 }}>
              <label>Salvar como modelo</label>
              <input
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder="Ex: Vaquinha dançando"
              />
            </div>
            <button onClick={saveModel} disabled={busy || !modelName.trim()}>
              💾 Salvar modelo
            </button>
          </div>
          <p style={{ color: "#9a9ac0", fontSize: 12, margin: "4px 0 0" }}>
            Guarda esta arte para reusar. Em <strong>Personagens</strong>, o botão
            "Criar a partir de modelo" monta um personagem novo com ela — sem gerar (nem pagar)
            de novo.
          </p>

          <div className="row" style={{ marginTop: 14 }}>
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

      {models.length > 0 && (
        <div className="card">
          <h3>Modelos salvos</h3>
          <p style={{ color: "#9a9ac0", fontSize: 13 }}>
            Artes prontas, guardadas para reusar. Um personagem novo sai de qualquer uma delas em
            <strong> Personagens → Criar a partir de modelo</strong>.
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {models.map((model) => (
              <div
                key={model.id}
                style={{
                  border: "1px solid #2f2f47",
                  borderRadius: 10,
                  padding: 10,
                  width: 200,
                  background: "#14141f",
                }}
              >
                {model.image_url ? (
                  <img
                    src={`${API_BASE}${model.image_url}`}
                    alt={model.name}
                    style={{ width: "100%", background: CHECKER, borderRadius: 6 }}
                  />
                ) : (
                  <div style={{ fontSize: 30, textAlign: "center", padding: 20 }}>🖼️</div>
                )}
                <strong style={{ display: "block", marginTop: 6, fontSize: 13 }}>{model.name}</strong>
                <div style={{ color: "#9a9ac0", fontSize: 12 }}>
                  {model.sprite_columns > 0
                    ? `${model.sprite_frame_count} quadros · ${model.sprite_fps} FPS`
                    : "imagem parada"}
                  {(model.sprite_clips?.length ?? 0) > 1 &&
                    ` · ${model.sprite_clips.filter((c) => c.kind === "gesture").length} gesto(s)`}
                  {model.hit_image_url && " · dano"}
                  {model.fire_image_url && " · ataque"}
                </div>
                <button
                  className="secondary"
                  onClick={() => removeModel(model)}
                  disabled={busy}
                  style={{ marginTop: 8, padding: "3px 10px", fontSize: 12 }}
                >
                  Excluir
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
