import { useState } from "react";
import { api, assetUrl } from "../api/client";
import SpritePreview from "./SpritePreview";

/** One movement with its own sheet, as the server stores it. */
export interface Movement {
  name: string;
  kind: "idle" | "gesture" | "hit" | "fire";
  image_url: string;
  columns: number;
  rows: number;
  frames: number;
  fps?: number;
  weight?: number;
  lift?: number;
}

interface Props {
  movements: Movement[];
  onChange: (movements: Movement[]) => void;
  /** Frames per second used by a movement that has none of its own. */
  baseFps?: number;
}

const KIND_LABEL: Record<Movement["kind"], string> = {
  idle: "Movimento base (loop)",
  gesture: "Gesto (de vez em quando)",
  hit: "Ao levar dano",
  fire: "Ao atacar",
};

/** Every movement on its own sheet, each with as many frames as it needs.
 *
 * Frames are replaced or added by sending either one sheet (its frames are
 * found automatically) or several image files at once (one frame each, in
 * file-name order -- frame_001.png, frame_002.png...). Every sheet is fitted
 * to the base movement on the server, so the character keeps its size and
 * position when the arena switches from one movement to another.
 */
export default function MovementEditor({ movements, onChange, baseFps = 10 }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState<Movement["kind"]>("gesture");

  const base = movements.find((m) => m.kind === "idle");

  /** Uploads the files and builds one movement from them. */
  const build = async (files: File[], target: Pick<Movement, "name" | "kind" | "fps" | "weight" | "lift">) => {
    const sorted = [...files].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    const urls: string[] = [];
    for (const [i, file] of sorted.entries()) {
      setBusy(`${target.name}: enviando ${i + 1} de ${sorted.length}…`);
      urls.push((await api.upload("/api/characters/upload", file)).url);
    }
    setBusy(`${target.name}: montando o sprite…`);
    const reference = base && !(target.kind === "idle" && base.name === target.name) ? base : base;
    const result = await api.post<{ movement: Movement; warnings: string[] }>("/api/sprites/movements/build", {
      name: target.name,
      kind: target.kind,
      image_urls: urls,
      fps: target.fps ?? 0,
      weight: target.weight ?? 1,
      lift: target.lift ?? 0,
      reference: reference
        ? { image_url: reference.image_url, columns: reference.columns, rows: reference.rows, frames: reference.frames }
        : undefined,
    });
    if (result.warnings.length) setError(result.warnings.join(" "));
    return result.movement;
  };

  const run = async (action: () => Promise<void>) => {
    setError("");
    setNotice("");
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const replaceFrames = (index: number, files: File[]) =>
    run(async () => {
      const current = movements[index];
      const built = await build(files, current);
      onChange(movements.map((m, i) => (i === index ? built : m)));
      setNotice(`"${current.name}" agora tem ${built.frames} quadros.`);
    });

  const addMovement = (files: File[]) =>
    run(async () => {
      const name =
        newKind === "idle" ? "base" : newKind === "gesture" ? newName.trim() || `gesto_${movements.length}` : newKind;
      const built = await build(files, { name, kind: newKind, fps: 0, weight: 2, lift: 0 });
      // One base, one hit, one fire: a second one replaces the first.
      const unique = newKind === "gesture" ? movements.filter((m) => m.name !== name) : movements.filter((m) => m.kind !== newKind);
      onChange([...unique, built]);
      setNewName("");
      setNotice(`Movimento "${name}" adicionado com ${built.frames} quadros.`);
    });

  const patch = (index: number, change: Partial<Movement>) =>
    onChange(movements.map((m, i) => (i === index ? { ...m, ...change } : m)));

  const remove = (index: number) => {
    const m = movements[index];
    if (m.kind === "idle" && movements.length > 1) {
      if (!window.confirm("Remover o movimento base? Os outros continuam, mas sem base o personagem volta à folha única.")) return;
    }
    onChange(movements.filter((_, i) => i !== index));
  };

  const filePicker = (label: string, onFiles: (files: File[]) => void, disabled = false) => (
    <label className="secondary" style={{ padding: "4px 10px", fontSize: 12, cursor: disabled ? "default" : "pointer" }}>
      {label}
      <input
        type="file"
        accept="image/*"
        multiple
        style={{ display: "none" }}
        disabled={disabled}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = "";
          if (files.length) onFiles(files);
        }}
      />
    </label>
  );

  return (
    <div>
      {movements.length === 0 && (
        <p style={{ color: "#9a9ac0", fontSize: 12 }}>
          Nenhum movimento separado ainda. Comece pelo <b>movimento base</b>: ele define o tamanho que
          todos os outros vão seguir.
        </p>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {movements.map((m, index) => (
          <div
            key={`${m.kind}-${m.name}-${index}`}
            style={{ border: "1px solid #2f2f47", borderRadius: 10, padding: 10, width: 250, background: "#14141f" }}
          >
            <div style={{ fontSize: 12, color: "#9a9ac0" }}>{KIND_LABEL[m.kind]}</div>
            {m.kind === "gesture" ? (
              <input
                value={m.name}
                style={{ width: "100%", margin: "4px 0" }}
                onChange={(e) => patch(index, { name: e.target.value.replace(/[^a-zA-Z0-9_-]/g, "_") })}
              />
            ) : (
              <strong style={{ display: "block", margin: "4px 0", fontSize: 13 }}>{m.name}</strong>
            )}
            <SpritePreview
              url={assetUrl(m.image_url) ?? ""}
              columns={m.columns}
              rows={m.rows}
              frameCount={m.frames}
              fps={m.fps && m.fps > 0 ? m.fps : baseFps}
              clips={[]}
              height={150}
              bare
            />
            <div className="row" style={{ marginTop: 6, gap: 6, alignItems: "center", fontSize: 12 }}>
              <span>{m.frames} quadros</span>
              <label style={{ fontSize: 12 }}>
                FPS{" "}
                <input
                  type="number"
                  min={0}
                  max={60}
                  value={m.fps ?? 0}
                  title="0 = usa o FPS do personagem"
                  style={{ width: 52 }}
                  onChange={(e) => patch(index, { fps: Number(e.target.value) })}
                />
              </label>
              {m.kind === "gesture" && (
                <label style={{ fontSize: 12 }} title="Quanto maior, mais vezes ele aparece">
                  freq.{" "}
                  <input
                    type="number"
                    min={0.1}
                    max={10}
                    step={0.5}
                    value={m.weight ?? 1}
                    style={{ width: 48 }}
                    onChange={(e) => patch(index, { weight: Number(e.target.value) })}
                  />
                </label>
              )}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
              {filePicker("Trocar quadros", (files) => replaceFrames(index, files), busy !== null)}
              <a className="secondary" style={{ padding: "4px 10px", fontSize: 12 }} href={assetUrl(m.image_url)} download>
                Baixar
              </a>
              <button className="secondary" style={{ padding: "4px 10px", fontSize: 12 }} onClick={() => remove(index)}>
                Remover
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="row" style={{ marginTop: 12, alignItems: "flex-end" }}>
        <select value={newKind} onChange={(e) => setNewKind(e.target.value as Movement["kind"])}>
          <option value="idle">Movimento base</option>
          <option value="gesture">Gesto</option>
          <option value="hit">Ao levar dano</option>
          <option value="fire">Ao atacar</option>
        </select>
        {newKind === "gesture" && (
          <input
            placeholder="nome do gesto (ex: danca)"
            value={newName}
            style={{ width: 170 }}
            onChange={(e) => setNewName(e.target.value.replace(/[^a-zA-Z0-9_-]/g, "_"))}
          />
        )}
        {filePicker("+ Adicionar movimento (folha ou vários PNG)", addMovement, busy !== null)}
      </div>
      <p style={{ color: "#9a9ac0", fontSize: 11, margin: "6px 0 0", lineHeight: 1.6 }}>
        Envie <b>uma folha</b> (as poses são encontradas sozinhas) ou <b>vários arquivos de uma vez</b>, um por
        quadro, na ordem do nome (quadro_01.png, quadro_02.png…). Mais quadros = movimento mais suave; 12 a 24
        quadros a 12–16 FPS costuma ficar bem natural.
      </p>
      {busy && <p style={{ color: "#9a9ac0", fontSize: 12 }}>{busy}</p>}
      {notice && <p style={{ color: "#4ade80", fontSize: 12 }}>{notice}</p>}
      {error && <p style={{ color: "#ff6b6b", fontSize: 12 }}>{error}</p>}
    </div>
  );
}
