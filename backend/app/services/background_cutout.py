"""Cutting a flat background out of a generated frame.

Image services rarely hand back real transparency. Asked to edit a PNG, they
answer with the character on a flat card -- white on one frame, black on the
next -- and that card does two kinds of damage:

* it shows up in the arena as a rectangle behind the character, and
* it makes the whole canvas look like "character" to the sheet composer,
  which measures a pose by its non-transparent area. A frame with a card
  seems enormous, gets shrunk to match the others, and the drawing inside it
  ends up visibly smaller than the frame that arrived clean.

Two ways to take the card off, chosen per frame:

* **Key colour.** The studio picks a card colour the character does not
  contain -- read from the reference's own palette, never a fixed magenta --
  and sends the reference already sitting on it, so the edit keeps it. Every
  pixel of that colour can then go, including the holes the character
  encloses (the gap between a tentacle and the body), and the blend at the
  edge is ramped and has the card's colour taken back out. The purple streaks
  of the old chroma attempt came from skipping exactly those two steps with a
  colour the character *did* come close to.

* **Border fill**, when the model ignored the key and painted white or black
  anyway. The fill starts at the edge and spreads only through connected
  pixels near the border's colour, so a white beard or a star on a shirt is
  never reached. It cannot clear enclosed holes and can leak into a part of
  the character that is the card's colour and touches the outline, which is
  why it is the fallback and not the plan.
"""

from __future__ import annotations

import logging
from collections import deque

import numpy as np
from PIL import Image, ImageFilter

logger = logging.getLogger("background_cutout")

#: How far (per channel) a pixel may stray from the border colour and still
#: be background. Enough for JPEG-ish noise and a faint vignette; not enough
#: to swallow a pale hat or a white beard that happens to touch the edge.
DEFAULT_TOLERANCE = 26

#: Past this the colour difference is fully "character". Between the two the
#: edge pixel is partly transparent -- that ramp is what removes the halo.
EDGE_SOFT_LIMIT = 90

#: If this much of the frame would vanish, the "background" is probably the
#: character itself. Leave the drawing alone rather than return a blank frame.
MAX_ERASED_FRACTION = 0.92

#: Below this share of the border agreeing on one colour, there is no flat
#: card to cut -- it is scenery, and scenery is not guessed at.
MIN_BORDER_AGREEMENT = 0.6

#: Card colours the studio may ask for. Magenta and purple are left out on
#: purpose: they are what the admin saw bleed through the character before.
KEY_CANDIDATES: list[tuple[int, int, int]] = [
    (0, 255, 0),    # green
    (0, 0, 255),    # blue
    (0, 255, 255),  # cyan
    (255, 255, 0),  # yellow
]

#: Key mode ramp: at or under KEY_INNER from the card -> transparent; at or
#: over KEY_OUTER -> fully the character; linear in between.
KEY_INNER = 40
KEY_OUTER = 110

#: How close the painted border must be to the requested key to trust it. A
#: model that ignored the request gets the border fill instead.
KEY_HONOURED = 80


def hex_colour(colour: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % colour


def pick_key_colour(reference: Image.Image) -> tuple[int, int, int]:
    """The card colour least like anything in the character.

    Read from the reference -- the admin's own PNG, or the first generated
    frame once its card is off -- so a green frog gets a blue card and a red
    octopus a green one, instead of every character getting the same colour
    and some of them losing half their body to it.
    """
    rgba = reference.convert("RGBA")
    rgba.thumbnail((256, 256))
    pixels = np.asarray(rgba).reshape(-1, 4)
    body = pixels[pixels[:, 3] > 200][:, :3].astype(np.int16)
    if len(body) == 0:
        return KEY_CANDIDATES[0]

    best, best_score = KEY_CANDIDATES[0], None
    for candidate in KEY_CANDIDATES:
        distance = np.abs(body - np.array(candidate, dtype=np.int16)).max(axis=1)
        # How much of the character would be at risk, then how close the
        # nearest part of it comes -- fewer at-risk pixels wins, then margin.
        score = (float((distance < KEY_OUTER + 20).mean()), -float(np.percentile(distance, 1)))
        if best_score is None or score < best_score:
            best, best_score = candidate, score
    return best


def on_key(image: Image.Image, key: tuple[int, int, int]) -> Image.Image:
    """The reference as the model should see it: already on the key card.

    Sent transparent, it comes back on whatever card the model fancies --
    white on one frame, black on the next. Sent on the key, an edit keeps
    the key, which is the colour this module knows how to take off.
    """
    card = Image.new("RGBA", image.size, key + (255,))
    card.alpha_composite(image.convert("RGBA"))
    return card


def already_transparent(image: Image.Image) -> bool:
    """True when the drawing arrived with real transparency of its own."""
    if image.mode != "RGBA":
        return False
    alpha = np.asarray(image.getchannel("A"))
    # A handful of soft pixels is not a cutout; a real one leaves a good part
    # of the frame empty.
    return bool((alpha < 16).mean() > 0.05)


def border_colour(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    """The colour the frame's edge is made of, and how much of it agrees."""
    h, w, _ = rgb.shape
    band = max(1, min(h, w) // 100)
    border = np.concatenate(
        [
            rgb[:band].reshape(-1, 3),
            rgb[-band:].reshape(-1, 3),
            rgb[:, :band].reshape(-1, 3),
            rgb[:, -band:].reshape(-1, 3),
        ]
    )
    # The median holds steady when a tentacle or a hat brim clips a corner.
    colour = np.median(border, axis=0)
    close = np.abs(border.astype(np.int16) - colour).max(axis=1) <= DEFAULT_TOLERANCE
    return colour, float(close.mean())


def _flood_from_border(similar: np.ndarray) -> np.ndarray:
    """Background is what the border reaches without crossing the character."""
    h, w = similar.shape
    reached = np.zeros((h, w), dtype=bool)
    queue: deque[tuple[int, int]] = deque()

    def seed(y: int, x: int) -> None:
        if similar[y, x] and not reached[y, x]:
            reached[y, x] = True
            queue.append((y, x))

    for x in range(w):
        seed(0, x)
        seed(h - 1, x)
    for y in range(h):
        seed(y, 0)
        seed(y, w - 1)

    # Scanline fill: each pop claims a whole horizontal run, which keeps a
    # 1.5-megapixel frame near a second instead of millions of single steps.
    while queue:
        y, x = queue.popleft()
        left = x
        while left > 0 and similar[y, left - 1] and not reached[y, left - 1]:
            left -= 1
            reached[y, left] = True
        right = x
        while right < w - 1 and similar[y, right + 1] and not reached[y, right + 1]:
            right += 1
            reached[y, right] = True
        for ny in (y - 1, y + 1):
            if not (0 <= ny < h):
                continue
            run = similar[ny, left : right + 1] & ~reached[ny, left : right + 1]
            if not run.any():
                continue
            starts = np.flatnonzero(run & ~np.concatenate(([False], run[:-1])))
            for offset in starts:
                nx = left + int(offset)
                reached[ny, nx] = True
                queue.append((ny, nx))
    return reached


def cut_out(
    image: Image.Image,
    tolerance: int = DEFAULT_TOLERANCE,
    key: tuple[int, int, int] | None = None,
) -> tuple[Image.Image, bool]:
    """Make a flat background transparent. Returns the image and whether it changed.

    Leaves the drawing untouched whenever it is not confident: art that
    already has transparency, a border that was never one colour, or a fill
    that would erase nearly everything.
    """
    rgba = image.convert("RGBA")
    if already_transparent(rgba):
        return rgba, False

    array = np.asarray(rgba).astype(np.float32)
    rgb = array[:, :, :3]

    colour, agreement = border_colour(rgb.astype(np.uint8))
    if agreement < MIN_BORDER_AGREEMENT:
        logger.info("fundo não removido: a borda não é de uma cor só (%.0f%%)", agreement * 100)
        return rgba, False

    distance = np.abs(rgb - colour).max(axis=2)

    if key is not None and float(np.abs(colour - np.array(key)).max()) <= KEY_HONOURED:
        return _key_out(array, colour, distance)
    background = _flood_from_border(distance <= tolerance)

    erased = float(background.mean())
    if erased > MAX_ERASED_FRACTION:
        logger.info("fundo não removido: apagaria %.0f%% da imagem", erased * 100)
        return rgba, False
    if erased < 0.01:
        return rgba, False

    # The edge band: pixels just outside the erased region. Anti-aliasing
    # blended the card's colour into them; left opaque they draw a thin white
    # (or black) outline around the character in the arena.
    grown = np.asarray(
        Image.fromarray((background * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))
    ) > 0
    edge = grown & ~background

    alpha = array[:, :, 3].copy()
    alpha[background] = 0
    if edge.any():
        # How much of each edge pixel is really character, judged by how far
        # its colour is from the card: near the card -> mostly transparent.
        coverage = np.clip(
            (distance[edge] - tolerance) / float(EDGE_SOFT_LIMIT - tolerance), 0.0, 1.0
        )
        alpha[edge] = alpha[edge] * coverage
        # Take the card's colour back out of what remains ("decontaminate"),
        # so a half-transparent edge pixel is not a pale ghost of the card.
        safe = np.maximum(coverage, 0.05)[:, None]
        rgb[edge] = np.clip((rgb[edge] - colour * (1.0 - safe)) / safe, 0, 255)

    out = np.dstack([rgb, alpha]).astype(np.uint8)
    logger.info("fundo removido: %.0f%% da imagem virou transparente", erased * 100)
    result = Image.fromarray(out, mode="RGBA")
    # The border fill cannot reach holes the character encloses; the studio
    # reads this to tell the admin which frame to look at.
    result.info["cut_mode"] = "border"
    return result, True


def _key_out(array: np.ndarray, colour: np.ndarray, distance: np.ndarray) -> tuple[Image.Image, bool]:
    """Remove every pixel of the key card, wherever it is.

    Global, not border-connected: the key was chosen because the character
    does not contain it, so a patch of it inside the silhouette is a hole in
    the drawing, not part of it. The ramp between KEY_INNER and KEY_OUTER is
    the anti-aliased edge; it becomes partial transparency, and the card's
    colour is taken back out of those pixels so no green (or blue) rim is
    left around the character.
    """
    coverage = np.clip((distance - KEY_INNER) / float(KEY_OUTER - KEY_INNER), 0.0, 1.0)
    erased = float((coverage == 0).mean())
    if erased > MAX_ERASED_FRACTION:
        logger.info("fundo não removido: a cor-chave apagaria %.0f%% da imagem", erased * 100)
        return Image.fromarray(array.astype(np.uint8), mode="RGBA"), False

    rgb = array[:, :, :3]
    alpha = array[:, :, 3] * coverage
    blended = (coverage > 0) & (coverage < 1)
    if blended.any():
        c = np.maximum(coverage[blended], 0.05)[:, None]
        rgb[blended] = np.clip((rgb[blended] - colour * (1.0 - c)) / c, 0, 255)

    out = np.dstack([rgb, alpha]).astype(np.uint8)
    logger.info("fundo removido pela cor-chave: %.0f%% da imagem", erased * 100)
    result = Image.fromarray(out, mode="RGBA")
    result.info["cut_mode"] = "key"
    return result, True
