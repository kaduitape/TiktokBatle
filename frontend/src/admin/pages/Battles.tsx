import { useEffect, useState } from "react";
import { api, assetUrl } from "../../api/client";

interface Character {
  id: string;
  name: string;
  image_url: string | null;
}

interface Gift {
  id: string;
  gift_key: string;
  name: string;
  icon: string;
  coins: number;
  action_type: string;
  active?: boolean;
}

interface Analysis {
  battle_name: string;
  counts: { alto: number; medio: number; dica: number };
  findings: { severity: "alto" | "medio" | "dica"; area: string; problem: string; fix: string }[];
}

interface Battle {
  id: string;
  name: string;
  mode: "character" | "team_pvp" | "tank_war";
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
  mode: "character" as "character" | "team_pvp" | "tank_war",
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
  const [notice, setNotice] = useState<{ kind: "erro" | "ok"; text: string } | null>(null);
  const [gifts, setGifts] = useState<Gift[]>([]);
  const [giftsFor, setGiftsFor] = useState<{ battle: Battle; selected: string[] } | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);

  /** Every action here talks to the server, and a failure used to be silent --
   * the button simply appeared dead. Route them all through this. */
  const run = async (what: string, action: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    setNotice(null);
    try {
      await action();
      if (done) setNotice({ kind: "ok", text: done });
    } catch (err) {
      setNotice({ kind: "erro", text: `${what}: ${err instanceof Error ? err.message : String(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const load = () => {
    api.get<Battle[]>("/api/battles").then(setBattles);
    api.get<Battle[]>("/api/battles/templates").then(setTemplates);
    api.get<Character[]>("/api/characters").then(setCharacters);
    api.get<Gift[]>("/api/gifts").then(setGifts);
  };
  useEffect(load, []);

  const save = () => {
    if (form.side_a_character_id === form.side_b_character_id) return;
    return run("Não consegui salvar a batalha", async () => {
      if (form.id) await api.put(`/api/battles/${form.id}`, form);
      else await api.post("/api/battles", form);
      setForm(empty);
      load();
    }, form.id ? "Batalha salva." : "Batalha criada.");
  };

  const remove = (battle: Battle) => {
    if (!window.confirm(`Excluir "${battle.name}"? O histórico dessa batalha (sessões, participantes e eventos) vai junto.`)) return;
    return run("Não consegui excluir a batalha", async () => {
      await api.del(`/api/battles/${battle.id}`);
      load();
    }, `Batalha "${battle.name}" excluída.`);
  };

  const openGifts = (battle: Battle) =>
    run("Não consegui ler os presentes da batalha", async () => {
      const current = await api.get<{ gift_ids: string[] }>(`/api/battles/${battle.id}/gifts`);
      setGiftsFor({ battle, selected: current.gift_ids });
    });

  const toggleGift = (giftId: string) =>
    setGiftsFor((state) =>
      state
        ? {
            ...state,
            selected: state.selected.includes(giftId)
              ? state.selected.filter((g) => g !== giftId)
              : [...state.selected, giftId],
          }
        : state
    );

  const saveGifts = () => {
    if (!giftsFor) return;
    return run("Não consegui salvar os presentes", async () => {
      await api.put(`/api/battles/${giftsFor.battle.id}/gifts`, { gift_ids: giftsFor.selected });
      setGiftsFor(null);
    }, "Presentes desta batalha salvos.");
  };

  const analyse = (battle: Battle) =>
    run("Não consegui analisar a batalha", async () => {
      setAnalysis(await api.get<Analysis>(`/api/battles/${battle.id}/analysis`));
    });

  const saveAsTemplate = (id: string) => {
    const templateName = window.prompt("Nome do modelo (ex: Política, Futebol, Games)…");
    if (!templateName) return;
    return run("Não consegui salvar o modelo", async () => {
      await api.post(`/api/battles/${id}/save-as-template?template_name=${encodeURIComponent(templateName)}`);
      load();
    }, `Modelo "${templateName}" salvo.`);
  };

  const instantiateTemplate = (id: string) => {
    const name = window.prompt("Nome da nova batalha baseada nesse modelo…");
    if (!name) return;
    return run("Não consegui criar a batalha a partir do modelo", async () => {
      await api.post(`/api/battles/from-template/${id}?name=${encodeURIComponent(name)}`);
      load();
    }, `Batalha "${name}" criada.`);
  };

  const removeTemplate = (t: Battle) => {
    if (!window.confirm(`Excluir o modelo "${(t as any).template_name || t.name}"?`)) return;
    return run("Não consegui excluir o modelo", async () => {
      await api.del(`/api/battles/${t.id}`);
      load();
    }, "Modelo excluído.");
  };

  const charFor = (id: string) => characters.find((c) => c.id === id);
  const charName = (id: string) => charFor(id)?.name || id;
  const selectedA = charFor(form.side_a_character_id);
  const selectedB = charFor(form.side_b_character_id);
  const selectedSidesReuseImage = Boolean(
    selectedA?.image_url && selectedA.image_url === selectedB?.image_url,
  );

  return (
    <div>
      <h1>Batalhas</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Uma batalha é só "Lado A x Lado B" — escolha quaisquer dois personagens cadastrados.
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

      {giftsFor && (
        <div className="card">
          <h3>Presentes de "{giftsFor.battle.name}"</h3>
          <p style={{ color: "#9a9ac0", fontSize: 13 }}>
            Marque quais presentes valem nesta batalha. <b>Nenhum marcado = todos valem</b>,
            que é como toda batalha funcionava até agora. Um presente desmarcado ainda pode ser
            enviado na live, mas não faz nada aqui.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gap: 6 }}>
            {gifts.map((g) => (
              <label key={g.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="checkbox"
                  checked={giftsFor.selected.includes(g.id)}
                  onChange={() => toggleGift(g.id)}
                />
                <span>{g.icon} {g.name}</span>
                <span className="pill">{g.coins}💰</span>
              </label>
            ))}
          </div>
          <div className="row" style={{ marginTop: 14 }}>
            <button onClick={saveGifts} disabled={busy}>Salvar presentes</button>
            <button className="secondary" onClick={() => setGiftsFor({ ...giftsFor, selected: [] })}>
              Marcar todos (limpar seleção)
            </button>
            <button className="secondary" onClick={() => setGiftsFor(null)}>Fechar</button>
          </div>
          <p style={{ color: "#6a6a8a", fontSize: 12, marginTop: 8 }}>
            {giftsFor.selected.length === 0
              ? "Nenhum marcado: esta batalha aceita todos os presentes."
              : `${giftsFor.selected.length} presente(s) marcados.`}
          </p>
        </div>
      )}

      {analysis && (
        <div className="card">
          <h3>Análise de "{analysis.battle_name}"</h3>
          <p style={{ color: "#9a9ac0", fontSize: 13 }}>
            {analysis.counts.alto} problema(s) sério(s), {analysis.counts.medio} de equilíbrio,{" "}
            {analysis.counts.dica} dica(s). A análise lê a configuração da batalha — ela não
            assiste à sua live, então não substitui a sua leitura das regras da plataforma.
          </p>
          {analysis.findings.length === 0 && (
            <p style={{ color: "#4ade80", fontSize: 13 }}>Nada a apontar nesta configuração.</p>
          )}
          {analysis.findings.map((f, i) => (
            <div
              key={i}
              style={{
                borderLeft: `3px solid ${f.severity === "alto" ? "#ff6b6b" : f.severity === "medio" ? "#e0a01b" : "#5a5a7a"}`,
                padding: "6px 0 6px 10px",
                marginBottom: 8,
              }}
            >
              <div style={{ fontSize: 13 }}>
                <span className="pill">{f.area}</span> {f.problem}
              </div>
              <div style={{ fontSize: 12, color: "#9a9ac0", marginTop: 2 }}>→ {f.fix}</div>
            </div>
          ))}
          <button className="secondary" onClick={() => setAnalysis(null)}>Fechar</button>
        </div>
      )}

      <div className="card">
        <h3>{form.id ? "Editar batalha" : "Nova batalha"}</h3>
        <label>Nome da batalha</label>
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />

        <label>Modo</label>
        <select
          value={form.mode}
          onChange={(e) => setForm({ ...form, mode: e.target.value as typeof form.mode })}
        >
          <option value="character">Personagens — espectadores atacam os dois personagens</option>
          <option value="team_pvp">Guerra de Times (PvP) — espectadores lutam entre si</option>
          <option value="tank_war">Guerra de Tanques — charges atiram, espectadores são as tropas</option>
        </select>
        <p style={{ color: "#6a6a8a", fontSize: 12, marginTop: 4 }}>
          {form.mode === "team_pvp" &&
            "Cada espectador vira um lutador com poder próprio: presentes fazem crescer e atacar, e quem zera o poder é eliminado."}
          {form.mode === "tank_war" &&
            "Eleições 2026: comente A ou B para entrar no respectivo lado. Só quem escolheu um lado aparece; a bolinha do perfil dispara o presente contra o personagem rival."}
          {form.mode === "character" &&
            "Modo clássico: os presentes tiram/dão XP dos personagens do Lado A e Lado B."}
        </p>

        <div className="form-grid">
          <div>
            <label>Lado A</label>
            <select value={form.side_a_character_id} onChange={(e) => setForm({ ...form, side_a_character_id: e.target.value })}>
              <option value="">selecione…</option>
              {characters.map((c) => (
                <option key={c.id} value={c.id} disabled={c.id === form.side_b_character_id}>{c.name}</option>
              ))}
            </select>
            {selectedA?.image_url && <img src={assetUrl(selectedA.image_url)} alt={`Imagem de ${selectedA.name}`} style={{ width: 72, height: 72, objectFit: "contain", marginTop: 8 }} />}

            <label>Máximo de bolinhas</label>
            <select value={form.max_players} onChange={(e) => setForm({ ...form, max_players: Number(e.target.value) })}>
              {[10, 20, 30, 50, 75, 100, 250, 500, 750, 1000].map((n) => (
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
                <option key={c.id} value={c.id} disabled={c.id === form.side_a_character_id}>{c.name}</option>
              ))}
            </select>
            {selectedB?.image_url && <img src={assetUrl(selectedB.image_url)} alt={`Imagem de ${selectedB.name}`} style={{ width: 72, height: 72, objectFit: "contain", marginTop: 8 }} />}

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

        {selectedSidesReuseImage && (
          <p style={{ color: "#ff8080", fontSize: 13 }}>
            Os dois lados estão usando a mesma imagem. Escolha ou cadastre uma figura diferente para o Lado B.
          </p>
        )}

        <div className="row" style={{ marginTop: 14 }}>
          <button onClick={save} disabled={!form.name || !form.side_a_character_id || !form.side_b_character_id || form.side_a_character_id === form.side_b_character_id || selectedSidesReuseImage}>
            {form.id ? "Salvar" : "Criar batalha"}
          </button>
          {form.id && <button className="secondary" onClick={() => setForm(empty)}>Cancelar</button>}
        </div>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Nome</th><th>Modo</th><th>Lado A</th><th>Lado B</th><th>Max</th><th></th>
            </tr>
          </thead>
          <tbody>
            {battles.map((b) => (
              <tr key={b.id}>
                <td>{b.name}</td>
                <td>
                  <span className="pill">{b.mode === "team_pvp" ? "⚔️ PvP" : b.mode === "tank_war" ? "🪖 Tanques" : "🎯 Personagens"}</span>
                </td>
                <td>{charName(b.side_a_character_id)}</td>
                <td>{charName(b.side_b_character_id)}</td>
                <td>{b.max_players}</td>
                <td className="row">
                  <a href={`#/arena?battle=${b.id}`} target="_blank" rel="noreferrer"><button>▶ Abrir</button></a>
                  <button className="secondary" onClick={() => setForm(b as any)}>Editar</button>
                  <button className="secondary" onClick={() => openGifts(b)}>🎁 Presentes</button>
                  <button className="secondary" onClick={() => analyse(b)}>🔍 Analisar</button>
                  <button className="secondary" onClick={() => saveAsTemplate(b.id)}>💾 Modelo</button>
                  <button className="secondary" onClick={() => remove(b)} disabled={busy}>Excluir</button>
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
                  <button className="secondary" onClick={() => removeTemplate(t)} disabled={busy}>Excluir</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
