import { useEffect, useState } from "react";
import { API_BASE, api } from "../../api/client";

interface Status {
  configured: boolean;
  model: string;
  max_poses: number;
}

interface Sheet {
  url: string;
  columns: number;
  rows: number;
  frame_count: number;
  frame_width: number;
  frame_height: number;
}

interface Character {
  id: string;
  name: string;
  [key: string]: unknown;
}

// A walk-cycle-ish loop that works for almost any caricature, so the page is
// useful before the admin writes a single pose of their own.
const DEFAULT_POSES = [
  "braços abaixados ao lado do corpo, boca fechada, expressão neutra",
  "braço direito a meio caminho, subindo, boca levemente aberta",
  "braço direito levantado na altura do ombro, boca aberta falando",
  "braço direito a meio caminho, descendo, boca levemente aberta",
];

export default function SpriteStudio() {
  const [status, setStatus] = useState<Status | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [description, setDescription] = useState("");
  const [poses, setPoses] = useState<string[]>(DEFAULT_POSES);
  const [columns, setColumns] = useState(0);
  const [fps, setFps] = useState(8);
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [targetId, setTargetId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [applied, setApplied] = useState("");

  useEffect(() => {
    api.get<Status>("/api/sprites/status").then(setStatus).catch(() => setStatus(null));
    api.get<Character[]>("/api/characters").then(setCharacters);
  }, []);

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
        image_url: sheet.url,
        sprite_columns: sheet.columns,
        sprite_rows: sheet.rows,
        sprite_frame_count: sheet.frame_count,
        sprite_fps: fps,
      });
      setApplied(`Folha aplicada em ${character.name}. Recarregue a Arena para ver.`);
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

      {status && !status.configured && (
        <div className="card" style={{ borderLeft: "4px solid #e0a01b" }}>
          <h3>Chave de imagem não configurada</h3>
          <p style={{ fontSize: 13, lineHeight: 1.6 }}>
            Pegue uma chave em <code>platform.openai.com</code>, coloque no arquivo{" "}
            <code>.env</code> do servidor e reinicie o backend:
          </p>
          <pre style={{ background: "#0d0d16", padding: 12, borderRadius: 6, fontSize: 12, overflowX: "auto" }}>
{`BATTLE_IMAGE_API_KEY=sk-...`}
          </pre>
          <p style={{ fontSize: 13 }}>
            Enquanto isso você ainda pode montar folhas à mão com{" "}
            <code>scripts/make_spritesheet.py</code> e subir em Personagens.
          </p>
        </div>
      )}

      <div className="card">
        <h3>Personagem</h3>
        <label>Descrição (vale para todas as poses)</label>
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
          <button onClick={generate} disabled={busy || !description.trim() || usablePoses === 0}>
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
          <h3>Folha gerada</h3>
          <img
            src={`${API_BASE}${sheet.url}`}
            alt="folha de sprites gerada"
            style={{
              maxWidth: "100%",
              background: "repeating-conic-gradient(#2a2a3a 0% 25%, #1b1b28 0% 50%) 50% / 24px 24px",
              borderRadius: 6,
            }}
          />
          <p style={{ fontSize: 13, marginTop: 10 }}>
            {sheet.columns} coluna(s) × {sheet.rows} linha(s) — {sheet.frame_count} quadros de{" "}
            {sheet.frame_width}×{sheet.frame_height} px
          </p>

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
            <a className="secondary" href={`${API_BASE}${sheet.url}`} target="_blank" rel="noreferrer">
              Baixar PNG
            </a>
          </div>
          {applied && <p style={{ color: "#4ade80", fontSize: 13, marginTop: 10 }}>{applied}</p>}
        </div>
      )}
    </div>
  );
}
