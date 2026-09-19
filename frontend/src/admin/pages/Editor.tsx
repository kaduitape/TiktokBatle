import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";

interface Battle {
  id: string;
  name: string;
  side_a_character_id: string;
  side_b_character_id: string;
}

interface Character {
  id: string;
  name: string;
  pos_x: number;
  pos_y: number;
  scale: number;
  team_color: string;
  flip_h: boolean;
  image_url: string | null;
  background_url: string | null;
  xp_max: number;
  shadow: boolean;
  outline: boolean;
  glow: boolean;
  idle_animation: string;
  hit_animation: string;
  heal_animation: string;
}

const PREVIEW_WIDTH = 320;
const PREVIEW_HEIGHT = (PREVIEW_WIDTH * 1920) / 1080;

export default function Editor() {
  const [battles, setBattles] = useState<Battle[]>([]);
  const [battleId, setBattleId] = useState("");
  const [charA, setCharA] = useState<Character | null>(null);
  const [charB, setCharB] = useState<Character | null>(null);
  const [dragging, setDragging] = useState<"A" | "B" | null>(null);
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState<{ kind: "erro" | "ok"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.get<Battle[]>("/api/battles").then((bs) => {
      setBattles(bs);
      if (bs[0]) setBattleId(bs[0].id);
    });
  }, []);

  useEffect(() => {
    const battle = battles.find((b) => b.id === battleId);
    if (!battle) return;
    api.get<Character>(`/api/characters/${battle.side_a_character_id}`).then(setCharA);
    api.get<Character>(`/api/characters/${battle.side_b_character_id}`).then(setCharB);
    setDirty(false);
  }, [battleId, battles]);

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging || !previewRef.current) return;
    const rect = previewRef.current.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    if (dragging === "A") setCharA((c) => (c ? { ...c, pos_x: x, pos_y: y } : c));
    else setCharB((c) => (c ? { ...c, pos_x: x, pos_y: y } : c));
    setDirty(true);
  };

  /** `apply` restarts the battle after saving, which republishes the whole
   * state to every open arena. Without it the OBS source keeps the positions
   * and sizes it drew when it was opened. */
  const save = async (apply: boolean) => {
    setBusy(true);
    setNotice(null);
    try {
      if (charA) await api.put(`/api/characters/${charA.id}`, charA);
      if (charB) await api.put(`/api/characters/${charB.id}`, charB);
      if (apply) await api.post(`/api/battles/${battleId}/restart`);
      setDirty(false);
      setNotice({
        kind: "ok",
        text: apply
          ? "Salvo e aplicado: a arena aberta no OBS já está com as novas posições."
          : "Salvo. Reinicie a batalha (ou use Salvar e aplicar) para a arena aberta mudar.",
      });
    } catch (err) {
      setNotice({ kind: "erro", text: `Não consegui salvar: ${err instanceof Error ? err.message : String(err)}` });
    } finally {
      setBusy(false);
    }
  };

  /** Position and size live on the character, so a character used by two
   * battles moves in both. Say so instead of letting it surprise somebody. */
  const sharedWith = (characterId: string | undefined) =>
    characterId
      ? battles.filter(
          (b) =>
            b.id !== battleId &&
            (b.side_a_character_id === characterId || b.side_b_character_id === characterId)
        )
      : [];

  return (
    <div>
      <h1>Editor de Arena</h1>
      <p style={{ color: "#9a9ac0", fontSize: 13 }}>
        Arraste os personagens dentro do preview 9:16 para posicioná-los. Salve para refletir na arena ao vivo.
      </p>

      <div className="card">
        <label>Batalha</label>
        <select value={battleId} onChange={(e) => setBattleId(e.target.value)}>
          {battles.map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>
      </div>

      <div className="card row" style={{ alignItems: "flex-start" }}>
        <div
          ref={previewRef}
          onPointerMove={onPointerMove}
          onPointerUp={() => setDragging(null)}
          onPointerLeave={() => setDragging(null)}
          style={{
            width: PREVIEW_WIDTH,
            height: PREVIEW_HEIGHT,
            background: "linear-gradient(#1a1a2a, #10101a)",
            position: "relative",
            border: "1px solid #33334c",
            borderRadius: 6,
            flexShrink: 0,
            touchAction: "none",
          }}
        >
          <div style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "#33334c" }} />
          <div style={{ position: "absolute", left: 6, top: 6, color: "#ffd700", fontWeight: 700, fontSize: 12 }}>A</div>
          <div style={{ position: "absolute", right: 6, top: 6, color: "#ffd700", fontWeight: 700, fontSize: 12 }}>B</div>

          {charA && (
            <div
              onPointerDown={() => setDragging("A")}
              style={{
                position: "absolute",
                left: charA.pos_x * PREVIEW_WIDTH,
                top: charA.pos_y * PREVIEW_HEIGHT,
                transform: "translate(-50%, -50%)",
                width: 60 * charA.scale,
                height: 60 * charA.scale,
                borderRadius: "50%",
                background: charA.team_color,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 11,
                fontWeight: 700,
                cursor: "grab",
                userSelect: "none",
                border: "2px solid #fff",
              }}
            >
              {charA.name.slice(0, 8)}
            </div>
          )}

          {charB && (
            <div
              onPointerDown={() => setDragging("B")}
              style={{
                position: "absolute",
                left: charB.pos_x * PREVIEW_WIDTH,
                top: charB.pos_y * PREVIEW_HEIGHT,
                transform: "translate(-50%, -50%)",
                width: 60 * charB.scale,
                height: 60 * charB.scale,
                borderRadius: "50%",
                background: charB.team_color,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 11,
                fontWeight: 700,
                cursor: "grab",
                userSelect: "none",
                border: "2px solid #fff",
              }}
            >
              {charB.name.slice(0, 8)}
            </div>
          )}
        </div>

        <div style={{ flex: 1 }}>
          {charA && (
            <div style={{ marginBottom: 16 }}>
              <strong>{charA.name} (Lado A)</strong>
              <div className="row">
                <span className="pill">x: {charA.pos_x.toFixed(2)}</span>
                <span className="pill">y: {charA.pos_y.toFixed(2)}</span>
              </div>
              <label>Tamanho: {(charA.scale * 100).toFixed(0)}%</label>
              <input
                type="range"
                min={0.2}
                max={2}
                step={0.05}
                value={charA.scale}
                onChange={(e) => {
                  setCharA({ ...charA, scale: Number(e.target.value) });
                  setDirty(true);
                }}
                style={{ width: "100%" }}
              />
              <div className="row">
                <input
                  type="number"
                  step="0.05"
                  min={0.1}
                  value={charA.scale}
                  onChange={(e) => {
                    setCharA({ ...charA, scale: Math.max(0.1, Number(e.target.value)) });
                    setDirty(true);
                  }}
                  style={{ width: 90 }}
                />
                <span className="pill">≈ {Math.round(900 * charA.scale)} px de altura na arena</span>
              </div>
              {sharedWith(charA.id).length > 0 && (
                <p style={{ color: "#e0a01b", fontSize: 12 }}>
                  Atenção: este personagem também é usado em{" "}
                  {sharedWith(charA.id).map((b) => b.name).join(", ")} — mudar aqui muda lá também.
                </p>
              )}
            </div>
          )}
          {charB && (
            <div>
              <strong>{charB.name} (Lado B)</strong>
              <div className="row">
                <span className="pill">x: {charB.pos_x.toFixed(2)}</span>
                <span className="pill">y: {charB.pos_y.toFixed(2)}</span>
              </div>
              <label>Tamanho: {(charB.scale * 100).toFixed(0)}%</label>
              <input
                type="range"
                min={0.2}
                max={2}
                step={0.05}
                value={charB.scale}
                onChange={(e) => {
                  setCharB({ ...charB, scale: Number(e.target.value) });
                  setDirty(true);
                }}
                style={{ width: "100%" }}
              />
              <div className="row">
                <input
                  type="number"
                  step="0.05"
                  min={0.1}
                  value={charB.scale}
                  onChange={(e) => {
                    setCharB({ ...charB, scale: Math.max(0.1, Number(e.target.value)) });
                    setDirty(true);
                  }}
                  style={{ width: 90 }}
                />
                <span className="pill">≈ {Math.round(900 * charB.scale)} px de altura na arena</span>
              </div>
              {sharedWith(charB.id).length > 0 && (
                <p style={{ color: "#e0a01b", fontSize: 12 }}>
                  Atenção: este personagem também é usado em{" "}
                  {sharedWith(charB.id).map((b) => b.name).join(", ")} — mudar aqui muda lá também.
                </p>
              )}
            </div>
          )}

          <div className="row" style={{ marginTop: 20 }}>
            <button onClick={() => save(true)} disabled={!dirty || busy}>
              Salvar e aplicar na arena
            </button>
            <button className="secondary" onClick={() => save(false)} disabled={!dirty || busy}>
              Só salvar
            </button>
          </div>
          {notice && (
            <p style={{ fontSize: 13, marginTop: 10, color: notice.kind === "erro" ? "#ff9b9b" : "#9ae6b4" }}>
              {notice.text}
            </p>
          )}
          <p style={{ color: "#6a6a8a", fontSize: 12, marginTop: 14 }}>
            XP, ranking, feed e legenda ainda usam posições fixas nesta versão — apenas os dois personagens
            são reposicionáveis pelo editor visual por enquanto.
          </p>
        </div>
      </div>
    </div>
  );
}
