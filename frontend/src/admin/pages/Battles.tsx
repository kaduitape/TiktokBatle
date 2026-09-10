import { useEffect, useState } from "react";
import { api } from "../../api/client";

interface Character {
  id: string;
  name: string;
}

interface Battle {
  id: string;
  name: string;
  side_a_character_id: string;
  side_b_character_id: string;
  max_players: number;
  one_ball_per_user: boolean;
  battle_time_seconds: number | null;
  sudden_death_enabled: boolean;
  auto_restart: boolean;
}

const empty = {
  name: "",
  side_a_character_id: "",
  side_b_character_id: "",
  max_players: 500,
  one_ball_per_user: true,
  battle_time_seconds: null as number | null,
  sudden_death_enabled: false,
  sudden_death_multiplier: 2,
  auto_restart: false,
  is_template: false,
  template_name: null as string | null,
  background_url: null as string | null,
};

export default function Battles() {
  const [battles, setBattles] = useState<Battle[]>([]);
  const [templates, setTemplates] = useState<Battle[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [form, setForm] = useState<typeof empty & { id?: string }>(empty);

  const load = () => {
    api.get<Battle[]>("/api/battles").then(setBattles);
    api.get<Battle[]>("/api/battles/templates").then(setTemplates);
    api.get<Character[]>("/api/characters").then(setCharacters);
  };
  useEffect(load, []);

  const save = async () => {
    if (form.id) await api.put(`/api/battles/${form.id}`, form);
    else await api.post("/api/battles", form);
    setForm(empty);
    load();
  };

  const remove = async (id: string) => {
    await api.del(`/api/battles/${id}`);
    load();
  };

  const saveAsTemplate = async (id: string) => {
    const templateName = window.prompt("Nome do modelo (ex: Política, Futebol, Games)…");
    if (!templateName) return;
    await api.post(`/api/battles/${id}/save-as-template?template_name=${encodeURIComponent(templateName)}`);
    load();
  };

  const instantiateTemplate = async (id: string) => {
    const name = window.prompt("Nome da nova batalha baseada nesse modelo…");
    if (!name) return;
    await api.post(`/api/battles/from-template/${id}?name=${encodeURIComponent(name)}`);
    load();
  };

  const removeTemplate = async (id: string) => {
    await api.del(`/api/battles/${id}`);
    load();
  };

  const charName = (id: string) => characters.find((c) => c.id === id)?.name || id;

  return (
    <div>
      <h1>Batalhas</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Uma batalha é só "Lado A x Lado B" — escolha quaisquer dois personagens cadastrados.
      </p>

      <div className="card">
        <h3>{form.id ? "Editar batalha" : "Nova batalha"}</h3>
        <label>Nome da batalha</label>
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />

        <div className="form-grid">
          <div>
            <label>Lado A</label>
            <select value={form.side_a_character_id} onChange={(e) => setForm({ ...form, side_a_character_id: e.target.value })}>
              <option value="">selecione…</option>
              {characters.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>

            <label>Máximo de bolinhas</label>
            <select value={form.max_players} onChange={(e) => setForm({ ...form, max_players: Number(e.target.value) })}>
              {[100, 250, 500, 750, 1000].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>

            <label>Tempo de batalha (segundos, vazio = sem limite)</label>
            <input
              type="number"
              value={form.battle_time_seconds ?? ""}
              onChange={(e) => setForm({ ...form, battle_time_seconds: e.target.value ? Number(e.target.value) : null })}
            />
          </div>
          <div>
            <label>Lado B</label>
            <select value={form.side_b_character_id} onChange={(e) => setForm({ ...form, side_b_character_id: e.target.value })}>
              <option value="">selecione…</option>
              {characters.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>

            <label>
              <input type="checkbox" checked={form.one_ball_per_user} onChange={(e) => setForm({ ...form, one_ball_per_user: e.target.checked })} /> Uma bolinha por usuário
            </label>
            <label>
              <input type="checkbox" checked={form.sudden_death_enabled} onChange={(e) => setForm({ ...form, sudden_death_enabled: e.target.checked })} /> Morte súbita ao acabar o tempo
            </label>
            {form.sudden_death_enabled && (
              <>
                <label>Multiplicador de dano na morte súbita</label>
                <input
                  type="number"
                  step="0.5"
                  min={1}
                  value={form.sudden_death_multiplier}
                  onChange={(e) => setForm({ ...form, sudden_death_multiplier: Number(e.target.value) })}
                />
              </>
            )}
            <label>
              <input type="checkbox" checked={form.auto_restart} onChange={(e) => setForm({ ...form, auto_restart: e.target.checked })} /> Reinício automático (nova rodada com contagem regressiva)
            </label>
          </div>
        </div>

        <div className="row" style={{ marginTop: 14 }}>
          <button onClick={save} disabled={!form.name || !form.side_a_character_id || !form.side_b_character_id}>
            {form.id ? "Salvar" : "Criar batalha"}
          </button>
          {form.id && <button className="secondary" onClick={() => setForm(empty)}>Cancelar</button>}
        </div>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Nome</th><th>Lado A</th><th>Lado B</th><th>Max</th><th></th>
            </tr>
          </thead>
          <tbody>
            {battles.map((b) => (
              <tr key={b.id}>
                <td>{b.name}</td>
                <td>{charName(b.side_a_character_id)}</td>
                <td>{charName(b.side_b_character_id)}</td>
                <td>{b.max_players}</td>
                <td className="row">
                  <a href={`#/arena?battle=${b.id}`} target="_blank" rel="noreferrer"><button>▶ Abrir</button></a>
                  <button className="secondary" onClick={() => setForm(b as any)}>Editar</button>
                  <button className="secondary" onClick={() => saveAsTemplate(b.id)}>💾 Salvar como modelo</button>
                  <button className="secondary" onClick={() => remove(b.id)}>Excluir</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Modelos salvos</h3>
        <p style={{ color: "#9a9ac0", fontSize: 13 }}>
          Configurações completas reutilizáveis (ex: "Política", "Futebol", "Games") — qualquer nome que o admin quiser.
        </p>
        {templates.length === 0 && <p style={{ color: "#6a6a8a", fontSize: 13 }}>Nenhum modelo salvo ainda.</p>}
        <table>
          <tbody>
            {templates.map((t) => (
              <tr key={t.id}>
                <td>{(t as any).template_name || t.name}</td>
                <td>{charName(t.side_a_character_id)} x {charName(t.side_b_character_id)}</td>
                <td className="row">
                  <button onClick={() => instantiateTemplate(t.id)}>▶ Usar este modelo</button>
                  <button className="secondary" onClick={() => removeTemplate(t.id)}>Excluir</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
