import { useEffect, useState } from "react";
import { api } from "../../api/client";

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

const empty: Omit<Gift, "id"> = {
  gift_key: "",
  tiktok_gift_id: null,
  name: "",
  icon: "🎁",
  action_type: "shot",
  value: -1,
  target_side: "A",
  coins: 1,
  animation_key: "shot",
  sound_key: "shot",
  combo_allowed: true,
  multiplier: 1,
  active: true,
};

export default function Gifts() {
  const [gifts, setGifts] = useState<Gift[]>([]);
  const [form, setForm] = useState<Omit<Gift, "id"> & { id?: string }>(empty);

  const load = () => api.get<Gift[]>("/api/gifts").then(setGifts);
  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    if (form.id) await api.put(`/api/gifts/${form.id}`, form);
    else await api.post("/api/gifts", form);
    setForm(empty);
    load();
  };

  const remove = async (id: string) => {
    await api.del(`/api/gifts/${id}`);
    load();
  };

  return (
    <div>
      <h1>Gerenciador de Presentes</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Nenhum presente fica preso ao código — edite ação, valor, alvo, ícone e combo livremente.
      </p>

      <div className="card">
        <h3>{form.id ? "Editar presente" : "Novo presente"}</h3>
        <div className="form-grid">
          <div>
            <label>Chave (gift_key, única)</label>
            <input value={form.gift_key} disabled={!!form.id} onChange={(e) => setForm({ ...form, gift_key: e.target.value })} />
            <label>ID do presente no TikTok</label>
            <input
              value={form.tiktok_gift_id ?? ""}
              inputMode="numeric"
              placeholder="ID capturado no assistente Ao vivo"
              onChange={(e) => setForm({ ...form, tiktok_gift_id: e.target.value.trim() || null })}
            />
            <label>Nome</label>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <label>Ícone (emoji)</label>
            <input value={form.icon} onChange={(e) => setForm({ ...form, icon: e.target.value })} />
            <label>Ação</label>
            <select value={form.action_type} onChange={(e) => setForm({ ...form, action_type: e.target.value as Gift["action_type"] })}>
              <option value="shot">Tiro</option>
              <option value="missile">Míssil</option>
              <option value="heal">Cura</option>
              <option value="super_heal">Super Cura</option>
              <option value="special">Especial</option>
            </select>
          </div>
          <div>
            <label>Valor de XP (negativo = dano, positivo = cura)</label>
            <input type="number" value={form.value} onChange={(e) => setForm({ ...form, value: Number(e.target.value) })} />
            <label>Alvo</label>
            <select value={form.target_side} onChange={(e) => setForm({ ...form, target_side: e.target.value as "A" | "B" })}>
              <option value="A">Lado A</option>
              <option value="B">Lado B</option>
            </select>
            <label>Moedas do TikTok</label>
            <input type="number" min="0" value={form.coins} onChange={(e) => setForm({ ...form, coins: Number(e.target.value) })} />
            <label>Multiplicador</label>
            <input type="number" step="0.1" value={form.multiplier} onChange={(e) => setForm({ ...form, multiplier: Number(e.target.value) })} />
            <label>
              <input type="checkbox" checked={form.combo_allowed} onChange={(e) => setForm({ ...form, combo_allowed: e.target.checked })} /> Permite combo
            </label>
            <label>
              <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Ativo
            </label>
          </div>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button onClick={save} disabled={!form.gift_key || !form.name}>{form.id ? "Salvar" : "Criar presente"}</button>
          {form.id && <button className="secondary" onClick={() => setForm(empty)}>Cancelar</button>}
        </div>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>ID TikTok</th>
              <th>Ícone</th><th>Nome</th><th>Ação</th><th>Valor</th><th>Alvo</th><th>Ativo</th><th></th>
            </tr>
          </thead>
          <tbody>
            {gifts.map((g) => (
              <tr key={g.id}>
                <td><code>{g.tiktok_gift_id || "não mapeado"}</code></td>
                <td style={{ fontSize: 20 }}>{g.icon}</td>
                <td>{g.name}</td>
                <td>{g.action_type}</td>
                <td style={{ color: g.value < 0 ? "#ff8080" : "#8be28b" }}>{g.value > 0 ? "+" : ""}{g.value}</td>
                <td>Lado {g.target_side}</td>
                <td>{g.active ? "✅" : "🚫"}</td>
                <td className="row">
                  <button className="secondary" onClick={() => setForm(g)}>Editar</button>
                  <button className="secondary" onClick={() => remove(g.id)}>Excluir</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
