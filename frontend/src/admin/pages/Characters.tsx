import { useEffect, useState } from "react";
import { api } from "../../api/client";

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
  xp_max: number;
}

const empty: Omit<Character, "id"> = {
  name: "",
  image_url: null,
  background_url: null,
  team_color: "#3498db",
  scale: 1,
  pos_x: 0.5,
  pos_y: 0.5,
  flip_h: false,
  shadow: true,
  outline: false,
  glow: false,
  xp_max: 100000,
};

export default function Characters() {
  const [list, setList] = useState<Character[]>([]);
  const [form, setForm] = useState<Omit<Character, "id"> & { id?: string }>(empty);
  const [saving, setSaving] = useState(false);

  const load = () => api.get<Character[]>("/api/characters").then(setList);
  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      if (form.id) {
        await api.put(`/api/characters/${form.id}`, form);
      } else {
        await api.post("/api/characters", form);
      }
      setForm(empty);
      load();
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    await api.del(`/api/characters/${id}`);
    load();
  };

  const upload = async (file: File, field: "image_url" | "background_url") => {
    const { url } = await api.upload("/api/characters/upload", file);
    setForm((f) => ({ ...f, [field]: url }));
  };

  return (
    <div>
      <h1>Personagens</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Nenhum personagem é fixo no código — cadastre qualquer Lado A/Lado B aqui.
      </p>

      <div className="card">
        <h3>{form.id ? "Editar personagem" : "Novo personagem"}</h3>
        <div className="form-grid">
          <div>
            <label>Nome</label>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />

            <label>Imagem (PNG transparente)</label>
            <input type="file" accept="image/*" onChange={(e) => e.target.files && upload(e.target.files[0], "image_url")} />
            {form.image_url && <div className="pill">{form.image_url}</div>}

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
              <th>Nome</th>
              <th>Cor</th>
              <th>XP máx</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {list.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td>
                  <span className="pill" style={{ background: c.team_color }}>&nbsp;&nbsp;&nbsp;</span>
                </td>
                <td>{c.xp_max.toLocaleString("pt-BR")}</td>
                <td className="row">
                  <button className="secondary" onClick={() => setForm(c)}>Editar</button>
                  <button className="secondary" onClick={() => remove(c.id)}>Excluir</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
