import { useRef, useState } from "react";
import { api, assetUrl } from "../api/client";

/** One named row of a sprite sheet, as far as sounds are concerned. */
interface ClipLike {
  name: string;
  kind?: "idle" | "gesture";
}

interface Props {
  clips: ClipLike[];
  sounds: Record<string, string>;
  onChange: (sounds: Record<string, string>) => void;
  /** Whether the character has reaction art; the sound works without it. */
  disabled?: boolean;
}

const LABELS: Record<string, string> = {
  base: "Movimento base (toca no máximo a cada 4 s)",
  hit: "Ao levar dano",
  fire: "Ao atacar",
};

/** A sound effect per movement: the loop, each gesture, taking a hit, firing.
 *
 * Keyed by the movement's name, not the sheet row, so reordering rows later
 * does not hand a jump's sound to a blink. The file is uploaded as soon as
 * it is picked and can be played right here, so nobody has to open the
 * arena to find out a sound is the wrong one.
 */
export default function MovementSounds({ clips, sounds, onChange, disabled }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const player = useRef<HTMLAudioElement | null>(null);

  const movements = [
    "base",
    ...clips.filter((c) => c.kind === "gesture").map((c) => c.name),
    "hit",
    "fire",
  ].filter((name, i, all) => all.indexOf(name) === i);

  const upload = async (movement: string, file: File) => {
    setBusy(movement);
    setError("");
    try {
      const { url } = await api.upload("/api/characters/upload", file);
      onChange({ ...sounds, [movement]: url });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const play = (url: string) => {
    player.current?.pause();
    player.current = new Audio(assetUrl(url));
    player.current.play().catch(() => setError("O navegador não conseguiu tocar esse arquivo."));
  };

  const remove = (movement: string) => {
    const next = { ...sounds };
    delete next[movement];
    onChange(next);
  };

  return (
    <div>
      {movements.map((movement) => (
        <div className="row" key={movement} style={{ marginBottom: 6, alignItems: "center" }}>
          <span style={{ minWidth: 190, fontSize: 13 }}>
            {LABELS[movement] ?? `Gesto: ${movement}`}
          </span>
          {sounds[movement] ? (
            <>
              <button className="secondary" onClick={() => play(sounds[movement])} disabled={disabled}>
                ▶ Ouvir
              </button>
              <button className="secondary" onClick={() => remove(movement)} disabled={disabled}>
                Remover
              </button>
            </>
          ) : (
            <label className="secondary" style={{ padding: "4px 10px", fontSize: 12, cursor: "pointer" }}>
              {busy === movement ? "Enviando…" : "+ Som"}
              <input
                type="file"
                accept="audio/*"
                style={{ display: "none" }}
                disabled={disabled || busy !== null}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) void upload(movement, file);
                }}
              />
            </label>
          )}
        </div>
      ))}
      {error && <p style={{ color: "#ff6b6b", fontSize: 12 }}>{error}</p>}
    </div>
  );
}
