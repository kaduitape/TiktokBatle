import { useEffect, useRef, useState } from "react";
import { api, assetUrl } from "../../api/client";

interface Battle {
  id: string;
  name: string;
  side_a_character_id: string;
  side_b_character_id: string;
  background_url: string | null;
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
  /** The full-arena backdrop. Lives on the battle, not the character, so it
   * is shown here for real -- positioning a character against a plain
   * gradient is a guess about where it will actually land on the backdrop. */
  const [background, setBackground] = useState<string | null>(null);
  /** Bottom strip the live overlay covers, in arena pixels (of 1920). */
  const [bottomSafe, setBottomSafe] = useState(0);
  /** The overlay image and where it sits, as fractions of the arena. */
  const [legend, setLegend] = useState({ url: "", x: 0.5, y: 0.9, scale: 1 });
  const [draggingLegend, setDraggingLegend] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .get<{
        bottom_safe_px?: number;
        legend_image_url?: string;
        legend_x?: number;
        legend_y?: number;
        legend_scale?: number;
      }>("/api/settings/arena")
      .then((l) => {
        setBottomSafe(Number(l?.bottom_safe_px ?? 0));
        setLegend({
          url: l?.legend_image_url ?? "",
          x: Number(l?.legend_x ?? 0.5),
          y: Number(l?.legend_y ?? 0.9),
          scale: Number(l?.legend_scale ?? 1),
        });
      })
      .catch(() => setBottomSafe(0));
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
    setBackground(battle.background_url);
    setDirty(false);
  }, [battleId, battles]);

  /** Uploaded and applied immediately, like a character's art: waiting for
   * "Salvar" to also swap the backdrop would make the preview lie about
   * what the OBS source shows in the meantime. */
  const uploadBackground = (file: File) =>
    run("Não consegui subir o fundo", async () => {
      const { url } = await api.upload("/api/characters/upload", file);
      const updated = await api.put<Battle>(`/api/battles/${battleId}/background`, { background_url: url });
      setBackground(updated.background_url);
      setBattles((list) => list.map((b) => (b.id === battleId ? { ...b, background_url: updated.background_url } : b)));
      setNotice({ kind: "ok", text: "Fundo aplicado. A arena aberta já está mostrando." });
    });

  const removeBackground = () =>
    run("Não consegui remover o fundo", async () => {
      const updated = await api.put<Battle>(`/api/battles/${battleId}/background`, { background_url: null });
      setBackground(updated.background_url);
      setBattles((list) => list.map((b) => (b.id === battleId ? { ...b, background_url: updated.background_url } : b)));
    });

  const onPointerMove = (e: React.PointerEvent) => {
    if (!previewRef.current) return;
    const rect = previewRef.current.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    if (draggingLegend) {
      setLegend((l) => ({ ...l, x, y }));
      setDirty(true);
      return;
    }
    if (!dragging) return;
    if (dragging === "A") setCharA((c) => (c ? { ...c, pos_x: x, pos_y: y } : c));
    else setCharB((c) => (c ? { ...c, pos_x: x, pos_y: y } : c));
    setDirty(true);
  };

  /** Shared wrapper so an upload failure shows up instead of vanishing. */
  const run = async (what: string, action: () => Promise<unknown>) => {
    setBusy(true);
    setNotice(null);
    try {
      await action();
    } catch (err) {
      setNotice({ kind: "erro", text: `${what}: ${err instanceof Error ? err.message : String(err)}` });
    } finally {
      setBusy(false);
    }
  };

  /** `apply` restarts the battle after saving, which republishes the whole
   * state to every open arena. Without it the OBS source keeps the positions
   * and sizes it drew when it was opened. */
  const save = async (apply: boolean) => {
    setBusy(true);
    setNotice(null);
    try {
      await api.put("/api/settings/arena", {
        bottom_safe_px: Math.round(bottomSafe),
        legend_image_url: legend.url,
        legend_x: legend.x,
        legend_y: legend.y,
        legend_scale: legend.scale,
      });
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

        <label style={{ marginTop: 14 }}>Fundo da arena</label>
        <p style={{ color: "#9a9ac0", fontSize: 12, margin: "2px 0 8px" }}>
          A imagem completa por trás dos personagens. Aplica na hora -- a arena aberta no OBS
          troca o fundo assim que você escolhe o arquivo, sem precisar de "Salvar" ou reiniciar.
        </p>
        <div className="row">
          <input
            type="file"
            accept="image/*"
            disabled={busy || !battleId}
            onChange={(e) => e.target.files?.[0] && uploadBackground(e.target.files[0])}
          />
          {background && (
            <button className="secondary" onClick={removeBackground} disabled={busy}>
              Remover fundo
            </button>
          )}
        </div>
      </div>

      <div className="card row" style={{ alignItems: "flex-start" }}>
        <div
          ref={previewRef}
          onPointerMove={onPointerMove}
          onPointerUp={() => {
            setDragging(null);
            setDraggingLegend(false);
          }}
          onPointerLeave={() => {
            setDragging(null);
            setDraggingLegend(false);
          }}
          style={{
            width: PREVIEW_WIDTH,
            height: PREVIEW_HEIGHT,
            background: background
              ? `url(${assetUrl(background)}) center / cover, linear-gradient(#1a1a2a, #10101a)`
              : "linear-gradient(#1a1a2a, #10101a)",
            position: "relative",
            border: "1px solid #33334c",
            borderRadius: 6,
            flexShrink: 0,
            touchAction: "none",
          }}
        >
          <div style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "#33334c" }} />
          {bottomSafe > 0 && (
            <div
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                bottom: 0,
                height: (bottomSafe / 1920) * PREVIEW_HEIGHT,
                background: "repeating-linear-gradient(45deg, #2a2a3a, #2a2a3a 6px, #23232f 6px, #23232f 12px)",
                borderTop: "1px dashed #6a6a8a",
                display: "flex",
                alignItems: "flex-start",
                justifyContent: "center",
                fontSize: 10,
                color: "#9a9ac0",
                paddingTop: 2,
              }}
            >
              chat cobre aqui
            </div>
          )}
          <div style={{ position: "absolute", left: 6, top: 6, color: "#ffd700", fontWeight: 700, fontSize: 12 }}>A</div>
          <div style={{ position: "absolute", right: 6, top: 6, color: "#ffd700", fontWeight: 700, fontSize: 12 }}>B</div>

          {legend.url && (
            <img
              src={assetUrl(legend.url)}
              alt="legenda"
              onPointerDown={(e) => {
                e.preventDefault();
                setDraggingLegend(true);
              }}
              style={{
                position: "absolute",
                left: legend.x * PREVIEW_WIDTH,
                top: legend.y * PREVIEW_HEIGHT,
                transform: "translate(-50%, -50%)",
                width: PREVIEW_WIDTH * 0.5 * legend.scale,
                cursor: "grab",
                userSelect: "none",
                zIndex: 3,
              }}
              draggable={false}
            />
          )}

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

          <div style={{ marginTop: 18, borderTop: "1px solid #2a2a3a", paddingTop: 14 }}>
            <strong>Altura livre no rodapé (chat)</strong>
            <p style={{ color: "#9a9ac0", fontSize: 12, margin: "4px 0 8px" }}>
              O chat do TikTok cobre a parte de baixo da tela. Reserve esse pedaço e as
              bolinhas, o feed e a legenda sobem juntos para ficarem acima dele.
            </p>
            <label>Reservado: {Math.round(bottomSafe)} px ({((bottomSafe / 1920) * 100).toFixed(0)}% da altura)</label>
            <input
              type="range"
              min={0}
              max={800}
              step={10}
              value={bottomSafe}
              onChange={(e) => {
                setBottomSafe(Number(e.target.value));
                setDirty(true);
              }}
              style={{ width: "100%" }}
            />
            <div className="row">
              {[0, 300, 420, 560].map((v) => (
                <button
                  key={v}
                  className="secondary"
                  onClick={() => {
                    setBottomSafe(v);
                    setDirty(true);
                  }}
                >
                  {v === 0 ? "sem reserva" : `${v} px`}
                </button>
              ))}
            </div>
          </div>

          <div style={{ marginTop: 18, borderTop: "1px solid #2a2a3a", paddingTop: 14 }}>
            <strong>Legenda em imagem (PNG)</strong>
            <p style={{ color: "#9a9ac0", fontSize: 12, margin: "4px 0 8px" }}>
              A legenda escrita pelo jogo saiu. Suba o seu PNG (fundo transparente) e
              arraste no preview para posicionar — ele aparece por cima da arena nos três modos.
            </p>
            <input
              type="file"
              accept="image/*"
              onChange={(e) =>
                e.target.files &&
                run("Não consegui subir a legenda", async () => {
                  const { url } = await api.upload("/api/characters/upload", e.target.files![0]);
                  setLegend((l) => ({ ...l, url }));
                  setDirty(true);
                })
              }
            />
            {legend.url && (
              <>
                <div className="row" style={{ marginTop: 8 }}>
                  <span className="pill">no preview: arraste para mover</span>
                  <button
                    className="secondary"
                    onClick={() => {
                      setLegend((l) => ({ ...l, url: "" }));
                      setDirty(true);
                    }}
                  >
                    Remover legenda
                  </button>
                </div>
                <label style={{ marginTop: 8 }}>Tamanho: {(legend.scale * 100).toFixed(0)}%</label>
                <input
                  type="range"
                  min={0.2}
                  max={2}
                  step={0.05}
                  value={legend.scale}
                  onChange={(e) => {
                    setLegend((l) => ({ ...l, scale: Number(e.target.value) }));
                    setDirty(true);
                  }}
                  style={{ width: "100%" }}
                />
                <div className="row">
                  <span className="pill">x: {legend.x.toFixed(2)}</span>
                  <span className="pill">y: {legend.y.toFixed(2)}</span>
                </div>
              </>
            )}
          </div>

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
            O XP e o ranking ficam no topo e não se mexem. O chão, as bolinhas dos perfis, o feed
            e a legenda acompanham a altura livre do rodapé definida acima.
          </p>
        </div>
      </div>
    </div>
  );
}
