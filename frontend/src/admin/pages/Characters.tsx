import { useEffect, useState } from "react";
import { api, assetUrl } from "../../api/client";

interface Character {
  id: string;
  name: string;
  image_url: string | null;
  background_url: string | null;
  team_color: string;
  scale: number;
  pos_x: number;
  pos_y: number;
  flip_h: boolean;
  shadow: boolean;
  outline: boolean;
  glow: boolean;
  sprite_columns: number;
  sprite_rows: number;
  sprite_frame_count: number;
  sprite_fps: number;
  hit_image_url: string | null;
  fire_image_url: string | null;
  /** Which row of the sheet is which movement, set by Gerar sprites. Empty
   * means the whole grid is one loop, which is how sheets worked before
   * gestures existed. */
  sprite_clips: Clip[];
  xp_max: number;
}

/** One named row of a sprite sheet. */
interface Clip {
  name: string;
  row: number;
  frames: number;
  kind?: "idle" | "gesture";
  weight?: number;
  fps?: number;
  lift?: number;
}

const empty: Omit<Character, "id"> = {
  name: "",
  image_url: null,
  background_url: null,
  team_color: "#3498db",
  scale: 1,
  // Keep a new character visible by default. The quick position buttons in
  // the form make it explicit which half of the arena it belongs to.
  pos_x: 0.25,
  pos_y: 0.5,
  flip_h: false,
  shadow: true,
  outline: false,
  glow: false,
  sprite_columns: 0,
  sprite_rows: 1,
  sprite_frame_count: 0,
  sprite_fps: 10,
  hit_image_url: null,
  fire_image_url: null,
  sprite_clips: [],
  xp_max: 100000,
};

/** An animated character saved in Gerar sprites, ready to be reused. */
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
}

export default function Characters() {
  const [list, setList] = useState<Character[]>([]);
  const [models, setModels] = useState<SpriteModel[]>([]);
  const [modelPick, setModelPick] = useState("");
  const [form, setForm] = useState<Omit<Character, "id"> & { id?: string }>(empty);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "erro" | "ok"; text: string } | null>(null);

  /** A failed request used to reject silently, which looked exactly like a
   * dead button. Everything that talks to the server reports back now. */
  const run = async (what: string, action: () => Promise<unknown>, done?: string) => {
    setSaving(true);
    setNotice(null);
    try {
      await action();
      if (done) setNotice({ kind: "ok", text: done });
    } catch (err) {
      setNotice({ kind: "erro", text: `${what}: ${err instanceof Error ? err.message : String(err)}` });
    } finally {
      setSaving(false);
    }
  };

  const load = () => api.get<Character[]>("/api/characters").then(setList);
  useEffect(() => {
    load();
    api
      .get<SpriteModel[]>("/api/sprites/models")
      .then(setModels)
      .catch(() => setModels([]));
  }, []);

  /** Starts a new character from a saved model.
   *
   * Only the art comes across. Position, scale, health and colour stay at
   * their defaults so the same model can be both sides of a battle, or the
   * base for several variants, without inheriting somebody else's placement.
   */
  const startFromModel = () => {
    const model = models.find((m) => m.id === modelPick);
    if (!model) return;
    setForm({
      ...empty,
      name: model.name,
      image_url: model.image_url,
      sprite_columns: model.sprite_columns,
      sprite_rows: model.sprite_rows,
      sprite_frame_count: model.sprite_frame_count,
      sprite_fps: model.sprite_fps,
      hit_image_url: model.hit_image_url,
      fire_image_url: model.fire_image_url,
      // Without the clip list the game plays every row as one loop, gestures
      // included -- the character would blink and hop as part of its walk.
      sprite_clips: model.sprite_clips ?? [],
    });
    setNotice({
      kind: "ok",
      text: `Personagem montado a partir de "${model.name}". Ajuste o nome e o lado, depois salve.`,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const save = () =>
    run("Não consegui salvar o personagem", async () => {
      if (form.id) await api.put(`/api/characters/${form.id}`, form);
      else await api.post("/api/characters", form);
      setForm(empty);
      load();
    }, form.id ? "Personagem salvo." : "Personagem criado.");

  const remove = (c: Character) => {
    if (!window.confirm(`Excluir "${c.name}"?`)) return;
    return run("Não consegui excluir", async () => {
      await api.del(`/api/characters/${c.id}`);
      load();
    }, `Personagem "${c.name}" excluído.`);
  };

  const upload = (file: File, field: "image_url" | "background_url" | "hit_image_url" | "fire_image_url") =>
    run("Não consegui subir a imagem", async () => {
      const { url } = await api.upload("/api/characters/upload", file);
      setForm((f) => ({ ...f, [field]: url }));
    });

  const placeOnSide = (side: "A" | "B") => {
    setForm((current) => ({
      ...current,
      pos_x: side === "A" ? 0.25 : 0.75,
      pos_y: 0.5,
      flip_h: side === "B",
    }));
  };

  return (
    <div>
      <h1>Personagens</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Nenhum personagem é fixo no código — cadastre qualquer Lado A/Lado B aqui.
      </p>

      {notice && (
        <div
          className="card"
          style={{
            borderLeft: `4px solid ${notice.kind === "erro" ? "#ff6b6b" : "#4ade80"}`,
            color: notice.kind === "erro" ? "#ff9b9b" : "#9ae6b4",
            fontSize: 13,
          }}
        >
          {notice.text}
        </div>
      )}

      {models.length > 0 && !form.id && (
        <div className="card">
          <h3>Criar a partir de modelo</h3>
          <p style={{ color: "#9a9ac0", fontSize: 13 }}>
            Modelos são as artes animadas que você salvou em <strong>Gerar sprites</strong>.
            Escolher um preenche a animação e as poses de dano e ataque aqui embaixo — você só
            dá o nome e escolhe o lado.
          </p>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <div style={{ flex: 1 }}>
              <label>Modelo</label>
              <select
                value={modelPick}
                onChange={(e) => setModelPick(e.target.value)}
                style={{ width: "100%" }}
              >
                <option value="">Escolha um modelo…</option>
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name}
                    {model.sprite_columns > 0 ? ` · ${model.sprite_frame_count} quadros` : ""}
                    {(model.sprite_clips?.filter((c) => c.kind === "gesture").length ?? 0) > 0
                      ? ` · ${model.sprite_clips.filter((c) => c.kind === "gesture").length} gestos`
                      : ""}
                    {model.hit_image_url ? " · dano" : ""}
                    {model.fire_image_url ? " · ataque" : ""}
                  </option>
                ))}
              </select>
            </div>
            <button onClick={startFromModel} disabled={!modelPick || saving}>
              Usar este modelo
            </button>
          </div>
          {modelPick && (
            <div className="row" style={{ marginTop: 12, alignItems: "center", gap: 12 }}>
              {(() => {
                const model = models.find((m) => m.id === modelPick);
                if (!model) return null;
                return (
                  <>
                    {model.image_url && (
                      <img
                        src={assetUrl(model.image_url)}
                        alt={model.name}
                        style={{
                          maxWidth: 320,
                          maxHeight: 110,
                          objectFit: "contain",
                          background:
                            "repeating-conic-gradient(#2a2a3a 0% 25%, #22222f 0% 50%) 50%/16px 16px",
                          borderRadius: 6,
                        }}
                      />
                    )}
                    {model.hit_image_url && (
                      <img
                        src={assetUrl(model.hit_image_url)}
                        alt="dano"
                        style={{ height: 70, objectFit: "contain" }}
                      />
                    )}
                    {model.fire_image_url && (
                      <img
                        src={assetUrl(model.fire_image_url)}
                        alt="ataque"
                        style={{ height: 70, objectFit: "contain" }}
                      />
                    )}
                  </>
                );
              })()}
            </div>
          )}
        </div>
      )}

      <div className="card">
        <h3>{form.id ? "Editar personagem" : "Novo personagem"}</h3>
        <div className="form-grid">
          <div>
            <label>Nome</label>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />

            <label>Imagem (PNG transparente)</label>
            <input type="file" accept="image/*" onChange={(e) => e.target.files && upload(e.target.files[0], "image_url")} />
            {form.image_url && (
              <div className="row" style={{ marginTop: 6 }}>
                <img src={assetUrl(form.image_url)} alt="Prévia do personagem" style={{ width: 54, height: 54, objectFit: "contain" }} />
                <span className="pill">Imagem selecionada</span>
              </div>
            )}

            <label>Animação (folha de sprites)</label>
            <p style={{ color: "#9a9ac0", fontSize: 12, margin: "2px 0 8px" }}>
              Suba uma imagem só com as poses lado a lado, todas do mesmo tamanho, e
              diga aqui como a grade está dividida. Deixe as colunas em <b>0</b> para
              usar a imagem como desenho parado.
            </p>
            <div className="row">
              <div style={{ flex: 1 }}>
                <label>Colunas</label>
                <input
                  type="number"
                  min={0}
                  value={form.sprite_columns}
                  onChange={(e) => setForm({ ...form, sprite_columns: Number(e.target.value) })}
                />
              </div>
              <div style={{ flex: 1 }}>
                <label>Linhas</label>
                <input
                  type="number"
                  min={1}
                  value={form.sprite_rows}
                  onChange={(e) => setForm({ ...form, sprite_rows: Number(e.target.value) })}
                />
              </div>
            </div>
            <div className="row">
              <div style={{ flex: 1 }}>
                <label>Quadros (0 = grade toda)</label>
                <input
                  type="number"
                  min={0}
                  value={form.sprite_frame_count}
                  onChange={(e) => setForm({ ...form, sprite_frame_count: Number(e.target.value) })}
                />
              </div>
              <div style={{ flex: 1 }}>
                <label>Quadros por segundo</label>
                <input
                  type="number"
                  min={1}
                  value={form.sprite_fps}
                  onChange={(e) => setForm({ ...form, sprite_fps: Number(e.target.value) })}
                />
              </div>
            </div>

            <label>Imagem ao levar dano (opcional)</label>
            <p style={{ color: "#9a9ac0", fontSize: 12, margin: "2px 0 6px" }}>
              Aparece por um instante quando o personagem toma um tiro. Sem ela, ele
              só pisca em vermelho como antes.
            </p>
            <input type="file" accept="image/*" onChange={(e) => e.target.files && upload(e.target.files[0], "hit_image_url")} />
            {form.hit_image_url && (
              <div className="row" style={{ marginTop: 6 }}>
                <img src={assetUrl(form.hit_image_url)} alt="Prévia de dano" style={{ width: 54, height: 54, objectFit: "contain" }} />
                <button className="secondary" onClick={() => setForm({ ...form, hit_image_url: null })}>Remover</button>
              </div>
            )}

            <label>Imagem ao disparar (opcional)</label>
            <p style={{ color: "#9a9ac0", fontSize: 12, margin: "2px 0 6px" }}>
              Usada na Guerra de Tanques, no instante do disparo de canhão.
            </p>
            <input type="file" accept="image/*" onChange={(e) => e.target.files && upload(e.target.files[0], "fire_image_url")} />
            {form.fire_image_url && (
              <div className="row" style={{ marginTop: 6 }}>
                <img src={assetUrl(form.fire_image_url)} alt="Prévia de disparo" style={{ width: 54, height: 54, objectFit: "contain" }} />
                <button className="secondary" onClick={() => setForm({ ...form, fire_image_url: null })}>Remover</button>
              </div>
            )}

            <label>Fundo</label>
            <input type="file" accept="image/*" onChange={(e) => e.target.files && upload(e.target.files[0], "background_url")} />
            {form.background_url && <div className="pill">{form.background_url}</div>}

            <label>Cor da equipe</label>
            <input type="color" value={form.team_color} onChange={(e) => setForm({ ...form, team_color: e.target.value })} />

            <label>XP máximo</label>
            <input
              type="number"
              value={form.xp_max}
              onChange={(e) => setForm({ ...form, xp_max: Number(e.target.value) })}
            />
          </div>
          <div>
            <label>Escala</label>
            <input
              type="number"
              step="0.05"
              value={form.scale}
              onChange={(e) => setForm({ ...form, scale: Number(e.target.value) })}
            />

            <label>Posição X (0-1)</label>
            <input
              type="number"
              step="0.05"
              min={0}
              max={1}
              value={form.pos_x}
              onChange={(e) => setForm({ ...form, pos_x: Number(e.target.value) })}
            />

            <label>Posição Y (0-1)</label>
            <input
              type="number"
              step="0.05"
              min={0}
              max={1}
              value={form.pos_y}
              onChange={(e) => setForm({ ...form, pos_y: Number(e.target.value) })}
            />

            <label>Posição inicial na arena</label>
            <div className="row">
              <button type="button" className="secondary" onClick={() => placeOnSide("A")}>Lado A</button>
              <button type="button" className="secondary" onClick={() => placeOnSide("B")}>Lado B</button>
            </div>

            <label>
              <input type="checkbox" checked={form.flip_h} onChange={(e) => setForm({ ...form, flip_h: e.target.checked })} /> Inverter horizontalmente
            </label>
            <label>
              <input type="checkbox" checked={form.shadow} onChange={(e) => setForm({ ...form, shadow: e.target.checked })} /> Sombra
            </label>
            <label>
              <input type="checkbox" checked={form.outline} onChange={(e) => setForm({ ...form, outline: e.target.checked })} /> Contorno
            </label>
            <label>
              <input type="checkbox" checked={form.glow} onChange={(e) => setForm({ ...form, glow: e.target.checked })} /> Brilho
            </label>
          </div>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button onClick={save} disabled={saving || !form.name}>
            {form.id ? "Salvar alterações" : "Criar personagem"}
          </button>
          {form.id && (
            <button className="secondary" onClick={() => setForm(empty)}>
              Cancelar
            </button>
          )}
        </div>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Imagem</th>
              <th>Nome</th>
              <th>Cor</th>
              <th>Animação</th>
              <th>XP máx</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {list.map((c) => (
              <tr key={c.id}>
                <td>{c.image_url ? <img src={assetUrl(c.image_url)} alt="" style={{ width: 42, height: 42, objectFit: "contain" }} /> : "—"}</td>
                <td>{c.name}</td>
                <td>
                  <span className="pill" style={{ background: c.team_color }}>&nbsp;&nbsp;&nbsp;</span>
                </td>
                <td>
                  {c.sprite_columns > 0
                    ? `${c.sprite_columns}x${c.sprite_rows} @ ${c.sprite_fps}fps`
                    : "parada"}
                </td>
                <td>{c.xp_max.toLocaleString("pt-BR")}</td>
                <td className="row">
                  <button className="secondary" onClick={() => setForm(c)}>Editar</button>
                  <button className="secondary" onClick={() => remove(c)} disabled={saving}>Excluir</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
