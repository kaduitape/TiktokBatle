"""Cutting a flat background out of a generated drawing.

Only OpenAI has a real transparency switch. Gemini and AIsa can only be asked
for a transparent background in words, and they often answer with the
character sitting on a flat white card. In the arena that card shows up as a
white rectangle behind the character.

So the background is removed here instead. The part that matters is *which*
white gets removed: a white cow on a white background has the same colour
inside and outside, and deleting every white pixel would hollow the animal
out. The fill therefore starts at the border and spreads only through
connected pixels -- white that the character encloses is never reached, so it
stays.
"""

from __future__ import annotations

import logging
from collections import deque

import numpy as np
from PIL import Image

logger = logging.getLogger("background_cutout")

#: How far a pixel may stray from the border colour and still count as
#: background. Generous enough for the soft gradient these models like to put
#: behind a character, tight enough not to swallow pale skin or clothing.
DEFAULT_TOLERANCE = 28

#: If this much of the picture would be erased, something went wrong -- the
#: "background" is probably the character itself. Better to leave the drawing
#: alone and let the admin see it than to hand back a blank frame.
MAX_ERASED_FRACTION = 0.92

#: Below this, the border was never a uniform colour in the first place, so
#: there is no flat background to cut.
MIN_BORDER_AGREEMENT = 0.6


def already_transparent(image: Image.Image) -> bool:
    """True when the drawing arrived with real transparency of its own."""
    if image.mode != "RGBA":
        return False
    alpha = np.asarray(image.getchannel("A"))
    # A handful of stray soft pixels is not a cutout; a real one leaves a
    # substantial part of the frame empty.
    return bool((alpha < 16).mean() > 0.05)


def _border_colour(rgb: np.ndarray) -> tuple[np.ndarray, float]:
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
    # The median is steadier than the mean when a corner clips the character.
    colour = np.median(border, axis=0)
    close = np.abs(border.astype(np.int16) - colour).max(axis=1) <= DEFAULT_TOLERANCE
    return colour, float(close.mean())


def _flood_from_border(similar: np.ndarray) -> np.ndarray:
    """Background is what the border can reach without crossing the character.

    A plain "every similar pixel" mask would also erase the character's own
    whites. Spreading from the edge keeps anything the drawing encloses.
    """
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

    # Scanline flood fill: each pop claims a whole horizontal run at once,
    # which is what keeps a 1.5-megapixel frame down to a fraction of a second
    # instead of millions of single-pixel steps.
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
            # One seed per contiguous stretch, not per pixel: the pop above
            # claims the whole stretch anyway, so queueing every pixel of it
            # was redundant work that dominated the runtime.
            starts = np.flatnonzero(run & ~np.concatenate(([False], run[:-1])))
            for offset in starts:
                nx = left + int(offset)
                reached[ny, nx] = True
                queue.append((ny, nx))
    return reached


def cut_out(image: Image.Image, tolerance: int = DEFAULT_TOLERANCE) -> tuple[Image.Image, bool]:
    """Make a flat background transparent. Returns the image and whether it changed.

    Leaves the drawing untouched whenever it is not confident: art that
    already has transparency, a border that was never one colour, or a fill
    that would erase nearly everything.
    """
    rgba = image.convert("RGBA")
    if already_transparent(rgba):
        return rgba, False

    array = np.asarray(rgba).copy()
    rgb = array[:, :, :3]

    colour, agreement = _border_colour(rgb)
    if agreement < MIN_BORDER_AGREEMENT:
        logger.info("fundo não removido: a borda não é de uma cor só (%.0f%%)", agreement * 100)
        return rgba, False

    similar = np.abs(rgb.astype(np.int16) - colour).max(axis=2) <= tolerance
    background = _flood_from_border(similar)

    erased = float(background.mean())
    if erased > MAX_ERASED_FRACTION:
        logger.info("fundo não removido: apagaria %.0f%% da imagem", erased * 100)
        return rgba, False
    if erased < 0.01:
        return rgba, False

    array[:, :, 3] = np.where(background, 0, array[:, :, 3])

    logger.info("fundo removido: %.0f%% da imagem virou transparente", erased * 100)
    return Image.fromarray(array, mode="RGBA"), True
