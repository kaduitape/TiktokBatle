import Phaser from "phaser";
import { API_BASE } from "../../api/client";

const PLACEHOLDER_COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#f1c40f", "#9b59b6", "#1abc9c", "#e67e22"];

function hashCode(str: string): number {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h << 5) - h + str.charCodeAt(i);
  return h;
}

function textureKeyFor(input: string): string {
  return `av_${Math.abs(hashCode(input))}`;
}

export function resolveAssetUrl(url: string | null): string | null {
  if (!url) return null;
  if (url.startsWith("http") || url.startsWith("data:")) return url;
  return `${API_BASE}${url}`;
}

function compositeCircular(
  scene: Phaser.Scene,
  key: string,
  sourceKey: string,
  size: number,
  ringColor: string
): void {
  const rt = scene.make.renderTexture({ width: size, height: size }, false);
  const maskShape = scene.make.graphics({}, false);
  maskShape.fillStyle(0xffffff);
  maskShape.fillCircle(size / 2, size / 2, size / 2 - 3);
  rt.setMask(maskShape.createGeometryMask());

  const img = scene.make.image({ key: sourceKey }, false);
  const scale = size / Math.min(img.width, img.height);
  img.setScale(scale).setPosition(size / 2, size / 2);
  rt.draw(img, size / 2, size / 2);
  rt.clearMask();

  const ring = scene.make.graphics({}, false);
  ring.lineStyle(4, Phaser.Display.Color.HexStringToColor(ringColor).color, 1);
  ring.strokeCircle(size / 2, size / 2, size / 2 - 2);
  rt.draw(ring, 0, 0);

  rt.saveTexture(key);
  rt.destroy();
  maskShape.destroy();
  ring.destroy();
  img.destroy();
}

function compositeFallback(
  scene: Phaser.Scene,
  key: string,
  size: number,
  ringColor: string,
  letter: string,
  colorSeed: string
): void {
  // Seeded on the whole name, not just the initial -- a live full of Marias
  // would otherwise render as one wall of identical circles.
  const bg = PLACEHOLDER_COLORS[Math.abs(hashCode(colorSeed)) % PLACEHOLDER_COLORS.length];

  const g = scene.make.graphics({}, false);
  g.fillStyle(Phaser.Display.Color.HexStringToColor(bg).color);
  g.fillCircle(size / 2, size / 2, size / 2 - 3);
  g.lineStyle(4, Phaser.Display.Color.HexStringToColor(ringColor).color, 1);
  g.strokeCircle(size / 2, size / 2, size / 2 - 2);

  // Baked through a RenderTexture rather than Graphics.generateTexture so the
  // initial can be drawn on top -- a viewer with no photo still reads as a
  // distinct person instead of an anonymous dot.
  const initial = scene.make
    .text(
      {
        x: size / 2,
        y: size / 2,
        text: letter,
        style: {
          fontFamily: "Segoe UI, sans-serif",
          fontSize: `${Math.round(size * 0.45)}px`,
          fontStyle: "bold",
          color: "#ffffff",
        },
      },
      false
    )
    .setOrigin(0.5);

  const rt = scene.make.renderTexture({ width: size, height: size }, false);
  rt.draw(g, 0, 0);
  rt.draw(initial, size / 2, size / 2);
  rt.saveTexture(key);

  rt.destroy();
  initial.destroy();
  g.destroy();
}

const pending = new Set<string>();

/** Bakes a circular, ring-bordered avatar texture once per
 * (url, team color, size) and caches it in Phaser's texture manager, so
 * rendering hundreds of avatars costs no per-frame masking. Shared by both
 * arena modes. */
export async function bakeAvatarTexture(
  scene: Phaser.Scene,
  url: string | null,
  ringColor: string,
  fallbackLetter: string,
  size: number,
  colorSeed = fallbackLetter
): Promise<string> {
  const key = textureKeyFor(`${url || `placeholder_${colorSeed}`}_${ringColor}_${size}`);
  if (scene.textures.exists(key)) return key;

  if (pending.has(key)) {
    await new Promise((r) => setTimeout(r, 60));
    return scene.textures.exists(key)
      ? key
      : bakeAvatarTexture(scene, url, ringColor, fallbackLetter, size, colorSeed);
  }
  pending.add(key);

  const resolved = resolveAssetUrl(url);
  try {
    if (resolved) {
      const loaderKey = `${key}_raw`;
      if (!scene.textures.exists(loaderKey)) {
        await new Promise<void>((resolve, reject) => {
          scene.load.setCORS("anonymous");
          scene.load.image(loaderKey, resolved);
          scene.load.once(`filecomplete-image-${loaderKey}`, () => resolve());
          scene.load.once("loaderror", () => reject(new Error("avatar load failed")));
          scene.load.start();
        });
      }
      compositeCircular(scene, key, loaderKey, size, ringColor);
    } else {
      compositeFallback(scene, key, size, ringColor, fallbackLetter, colorSeed);
    }
  } catch {
    compositeFallback(scene, key, size, ringColor, fallbackLetter, colorSeed);
  }

  pending.delete(key);
  return key;
}
