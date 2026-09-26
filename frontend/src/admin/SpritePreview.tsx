import { useEffect, useMemo, useRef, useState } from "react";

/** One named row of a sprite sheet, as the game reads it. */
export interface PreviewClip {
  name: string;
  row: number;
  frames: number;
  kind?: "idle" | "gesture";
  fps?: number;
  lift?: number;
}

interface Props {
  /** Absolute URL of the sheet. */
  url: string;
  columns: number;
  rows: number;
  frameCount: number;
  fps: number;
  clips: PreviewClip[];
  height?: number;
  /** Tank War holds a still frame and only plays gestures. */
  gesturesOnly?: boolean;
}

const CHECKER = "repeating-conic-gradient(#2a2a3a 0% 25%, #1b1b28 0% 50%) 50% / 24px 24px";

/** Plays a generated sheet the way the arena will play it.
 *
 * Judging an animation from a grid of stills is guesswork: whether the loop
 * closes, whether a gesture reads, whether the feet stay planted. All of that
 * is obvious in two seconds of movement and invisible in a contact sheet, and
 * finding out in the arena means a deploy per attempt.
 *
 * It draws straight from the PNG rather than going through Phaser: the sheet
 * is sliced by dividing the image by the grid, which is exactly what the game
 * does, so what plays here is what plays there.
 */
export default function SpritePreview({
  url, columns, rows, frameCount, fps, clips, height = 260, gesturesOnly = false,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [playing, setPlaying] = useState<string | null>(null);

  /** The clips to offer, falling back to the whole grid as one loop -- which
   * is what a sheet without a clip list has always been. */
  const list = useMemo<PreviewClip[]>(() => {
    const declared = (clips ?? []).filter((c) => c.row < Math.max(1, rows));
    if (declared.length) return declared;
    const cells = Math.max(1, columns) * Math.max(1, rows);
    return [{ name: "folha inteira", row: 0, frames: frameCount > 0 ? Math.min(frameCount, cells) : cells, kind: "idle" }];
  }, [clips, columns, rows, frameCount]);

  const base = useMemo(() => list.find((c) => c.kind !== "gesture") ?? list[0], [list]);
  const gestures = useMemo(() => list.filter((c) => c.kind === "gesture"), [list]);

  useEffect(() => {
    setReady(false);
    setFailed(false);
    const image = new Image();
    // Deliberately no crossOrigin: the card above already loaded this file
    // through a plain <img>, and the cached response carries no CORS header,
    // so asking for one here fails the load outright. Nothing reads the
    // canvas back -- it is only drawn to -- so tainting it costs nothing.
    image.onload = () => { imageRef.current = image; setReady(true); };
    image.onerror = () => setFailed(true);
    image.src = url;
    return () => { image.onload = null; image.onerror = null; };
  }, [url]);

  useEffect(() => {
    if (!ready) return;
    const canvas = canvasRef.current;
    const image = imageRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !image || !context) return;

    const cols = Math.max(1, columns);
    const rowCount = Math.max(1, rows);
    const frameWidth = image.naturalWidth / cols;
    const frameHeight = image.naturalHeight / rowCount;
    const scale = height / frameHeight;
    canvas.width = Math.max(1, Math.round(frameWidth * scale));
    canvas.height = height;

    // A gesture owns the sprite until it ends, then hands it back -- the same
    // handover the arena does, so the preview cannot look calmer than the game.
    let clip = playing ? list.find((c) => c.name === playing) ?? base : base;
    let frame = 0;
    let last = performance.now();
    let raf = 0;
    const still = gesturesOnly && clip === base;

    const draw = (now: number) => {
      const rate = Math.max(1, clip?.fps || fps || 8);
      if (!still && now - last >= 1000 / rate) {
        last = now;
        frame += 1;
        if (frame >= Math.max(1, clip?.frames ?? 1)) {
          if (clip !== base && clip?.kind === "gesture") {
            clip = base;
            setPlaying(null);
          }
          frame = 0;
        }
      }

      const column = Math.min(frame, cols - 1);
      const lift = clip?.lift ? Math.sin((frame / Math.max(1, clip.frames)) * Math.PI) * clip.lift * canvas.height : 0;
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.drawImage(
        image,
        column * frameWidth, (clip?.row ?? 0) * frameHeight, frameWidth, frameHeight,
        0, -lift, canvas.width, canvas.height,
      );
      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [ready, url, columns, rows, fps, height, playing, list, base, gesturesOnly]);

  if (failed) {
    return <p style={{ color: "#ff9b9b", fontSize: 12 }}>Não consegui carregar a folha para a prévia.</p>;
  }

  return (
    <div>
      <canvas
        ref={canvasRef}
        style={{ background: CHECKER, borderRadius: 8, display: "block", height }}
      />
      <div className="gift-filters" style={{ marginTop: 8 }}>
        <span style={{ color: "#9a9ac0", fontSize: 12 }}>
          {gesturesOnly ? "Parado (Guerra de Tanques) — toque um gesto:" : "Tocando o movimento base."}
        </span>
        {gestures.map((gesture) => (
          <button
            key={gesture.name}
            className={`chip ${playing === gesture.name ? "on" : ""}`}
            onClick={() => setPlaying(gesture.name)}
            disabled={playing === gesture.name}
          >
            ▶ {gesture.name}
          </button>
        ))}
        {!gestures.length && (
          <span style={{ color: "#9a9ac0", fontSize: 12 }}>Sem gestos nesta folha.</span>
        )}
      </div>
    </div>
  );
}
