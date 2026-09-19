import { useEffect, useState } from "react";
import { api } from "../../api/client";

interface Track {
  id: string;
  name: string;
  file_url: string;
  category: "normal" | "danger" | "victory" | "defeat";
  order_index: number;
}

interface Mixer {
  music: number;
  shots: number;
  explosions: number;
  alerts: number;
  ui: number;
  victory: number;
}

const CATEGORY_LABEL: Record<string, string> = {
  normal: "Normal",
  danger: "Perigo (XP baixo)",
  victory: "Vitória",
  defeat: "Derrota",
};

export default function Music() {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [name, setName] = useState("");
  const [category, setCategory] = useState<Track["category"]>("normal");
  const [fileUrl, setFileUrl] = useState("");
  const [mixer, setMixer] = useState<Mixer>({ music: 30, shots: 80, explosions: 80, alerts: 70, ui: 50, victory: 80 });
  const [notice, setNotice] = useState<{ kind: "erro" | "ok"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.get<Track[]>("/api/music").then(setTracks);
  useEffect(() => {
    load();
    api.get<Mixer>("/api/settings/audio_mixer").then(setMixer);
  }, []);

  /** Same silent-failure trap the other pages had: a rejected request just
   * disappeared and the button looked broken. */
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

  const upload = (file: File) =>
    run("Não consegui subir a música", async () => {
      const { url } = await api.upload("/api/music/upload", file);
      setFileUrl(url);
    });

  const addTrack = () => {
    if (!name || !fileUrl) return;
    return run("Não consegui adicionar a faixa", async () => {
      await api.post("/api/music", { name, file_url: fileUrl, category, order_index: 0 });
      setName("");
      setFileUrl("");
      load();
    }, "Faixa adicionada.");
  };

  const remove = (id: string, trackName: string) => {
    if (!window.confirm(`Excluir a faixa "${trackName}"?`)) return;
    return run("Não consegui excluir a faixa", async () => {
      await api.del(`/api/music/${id}`);
      load();
    }, "Faixa excluída.");
  };

  const saveMixer = () =>
    run("Não consegui salvar o mixer", async () => {
      await api.put("/api/settings/audio_mixer", mixer);
    }, "Mixer salvo.");

  return (
    <div>
      <h1>Músicas &amp; Mixer de Áudio</h1>
      {notice && (
        <p style={{ fontSize: 13, color: notice.kind === "erro" ? "#ff9b9b" : "#9ae6b4" }}>{notice.text}</p>
      )}
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Upload de trilhas por categoria (normal / perigo / vitória / derrota) — a arena troca de faixa sozinha
        conforme o XP cai. Efeitos de tiro/míssil/cura/combo já tocam sintetizados, sem precisar de arquivo.
      </p>

      <div className="card">
        <h3>Adicionar música</h3>
        <div className="form-grid">
          <div>
            <label>Nome</label>
            <input value={name} onChange={(e) => setName(e.target.value)} />
            <label>Categoria</label>
            <select value={category} onChange={(e) => setCategory(e.target.value as Track["category"])}>
              {Object.entries(CATEGORY_LABEL).map(([k, label]) => (
                <option key={k} value={k}>{label}</option>
              ))}
            </select>
          </div>
          <div>
            <label>Arquivo (MP3/WAV/OGG)</label>
            <input type="file" accept="audio/*" onChange={(e) => e.target.files && upload(e.target.files[0])} />
            {fileUrl && <div className="pill">{fileUrl}</div>}
          </div>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button onClick={addTrack} disabled={!name || !fileUrl}>Adicionar à playlist</button>
        </div>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr><th>Nome</th><th>Categoria</th><th></th></tr>
          </thead>
          <tbody>
            {tracks.map((t) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td>{CATEGORY_LABEL[t.category]}</td>
                <td><button className="secondary" onClick={() => remove(t.id, t.name)} disabled={busy}>Excluir</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {tracks.length === 0 && <p style={{ color: "#6a6a8a", fontSize: 13 }}>Nenhuma música cadastrada ainda — a arena roda sem BGM até adicionar uma.</p>}
      </div>

      <div className="card">
        <h3>🔊 Mixer</h3>
        {(Object.keys(mixer) as (keyof Mixer)[]).map((k) => (
          <div key={k} style={{ marginBottom: 8 }}>
            <label>{k} — {mixer[k]}%</label>
            <input
              type="range"
              min={0}
              max={100}
              value={mixer[k]}
              onChange={(e) => setMixer({ ...mixer, [k]: Number(e.target.value) })}
              style={{ width: "100%" }}
            />
          </div>
        ))}
        <div className="row" style={{ marginTop: 10 }}>
          <button onClick={saveMixer}>Salvar mixer</button>
        </div>
      </div>
    </div>
  );
}
