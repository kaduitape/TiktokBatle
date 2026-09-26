"""Reading a sprite sheet somebody already has.

A sheet made elsewhere is rarely a clean grid. Poses drift inside their
cells, rows have different lengths, some frames sit on a white card and
others on nothing, and the grid itself is unknown. Asking the admin for
columns and rows only works when the answer is exact -- one pixel off and
the game slices through a character.

So the grid is not asked for, it is found. Every separate figure on the
sheet is a frame; figures that share a height band are a row; rows read top
to bottom and frames left to right. Each frame is cleaned on its own, which
is what makes a mixed sheet -- some frames on a card, some already
transparent -- come out uniform. The frames then go through the same
composer the AI studio uses, so an imported sheet gets the same equal cells,
the same size normalisation and the same head alignment as a generated one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

from app.services.background_cutout import already_transparent, cut_out

logger = logging.getLogger("sprite_import")

#: Detection runs on a copy no larger than this; frames are cut from the
#: full-resolution image afterwards, so nothing is lost to the shrink.
DETECT_MAX_SIDE = 1200

#: A figure smaller than this share of the median one is not a frame -- a
#: speck, a stray shadow, a watermark -- and is folded into its nearest
#: neighbour or dropped.
MIN_FRAME_SHARE = 0.18

#: Two figures are in the same row when their heights overlap by at least
#: this share of the shorter one.
ROW_OVERLAP = 0.4

ALPHA_VISIBLE = 24


@dataclass
class DetectedFrame:
    image: Image.Image  # cleaned, cropped to the figure
    box: tuple[int, int, int, int]  # where it was on the sheet, full resolution
    cleaned: str  # "none" | "key" | "border" | "kept"


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) spans of True in a boolean row."""
    padded = np.concatenate(([False], row, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2], edges[1::2]))


def _label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Connected components of a boolean mask, 8-connected, by row runs.

    Run-based union-find: a sheet row holds a handful of runs, not thousands
    of pixels, so this stays fast in plain Python without SciPy.
    """
    h, _ = mask.shape
    parent: list[int] = [0]

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    labels = np.zeros(mask.shape, dtype=np.int32)
    previous: list[tuple[int, int, int]] = []
    for y in range(h):
        current: list[tuple[int, int, int]] = []
        for start, end in _runs(mask[y]):
            label = 0
            for p_start, p_end, p_label in previous:
                # 8-connectivity: a diagonal touch counts.
                if p_start <= end and start <= p_end:
                    if label == 0:
                        label = find(p_label)
                    else:
                        a, b = find(label), find(p_label)
                        if a != b:
                            parent[max(a, b)] = min(a, b)
                            label = min(a, b)
            if label == 0:
                parent.append(len(parent))
                label = len(parent) - 1
            labels[y, start:end] = label
            current.append((start, end, label))
        previous = current

    roots = np.array([find(i) for i in range(len(parent))], dtype=np.int32)
    labels = roots[labels]
    unique = np.unique(labels[labels > 0])
    remap = np.zeros(len(parent), dtype=np.int32)
    remap[unique] = np.arange(1, len(unique) + 1, dtype=np.int32)
    return remap[labels], len(unique)


def _visible_mask(sheet: Image.Image) -> tuple[Image.Image, np.ndarray]:
    """The sheet with any whole-sheet card removed, and what is on it."""
    rgba = sheet.convert("RGBA")
    if not already_transparent(rgba):
        # One card behind everything: take it off first, or the whole sheet
        # would be a single figure.
        rgba, _changed = cut_out(rgba)
    return rgba, np.asarray(rgba.getchannel("A")) > ALPHA_VISIBLE


def _split(profile: np.ndarray, low: float = 0.15) -> list[tuple[int, int]]:
    """Cut a projection profile at its valleys; [start, end) spans between.

    A valley is a stretch where the profile falls under ``low`` of the
    profile's typical bulk (its 90th percentile), and the cut goes through
    its lowest point. Neither a zero-width gap nor a truly empty band is
    required: on a tight sheet a tentacle or a stray line always crosses the
    boundary between two rows, so the boundary is only ever *nearly* empty.
    Empty margins at either end are trimmed.
    """
    nonzero = profile[profile > 0]
    if len(nonzero) == 0:
        return []
    peak = float(np.percentile(nonzero, 90))
    valley = profile < max(1.0, low * peak)

    cuts: list[int] = []
    for start, end in _runs(valley):
        cuts.append(start + int(np.argmin(profile[start:end])))

    edges = [0, *cuts, len(profile)]
    spans: list[tuple[int, int]] = []
    for a, b in zip(edges[:-1], edges[1:]):
        filled = np.flatnonzero(profile[a:b] > 0)
        if len(filled):
            spans.append((a + int(filled[0]), a + int(filled[-1]) + 1))
    return [span for span in spans if span[1] > span[0]]


def _mass(profile: np.ndarray, span: tuple[int, int]) -> float:
    return float(profile[span[0] : span[1]].sum())


def _assign_parts(small: np.ndarray, cells: list[tuple[int, int, int, int]]) -> list[np.ndarray]:
    """One mask per cell, every part of the sheet given to exactly one cell.

    A part that lies mostly in one cell goes there whole, even where it
    sticks out of it -- a tentacle reaching into the next row stays attached
    to its octopus. A part genuinely shared between cells (a floor shadow
    touching the hat of the figure below) is split along the cell boundary
    instead, so neither figure takes the other with it. Doing this per cell,
    with only a window of the sheet in view, let both neighbours claim the
    same shadow and produced overlapping frames.
    """
    labels, count = _label(small)
    masks = [np.zeros(small.shape, dtype=bool) for _ in cells]
    if count == 0:
        return masks

    total = np.bincount(labels.ravel(), minlength=count + 1)
    per_cell = np.zeros((len(cells), count + 1), dtype=np.int64)
    for i, (r0, r1, c0, c1) in enumerate(cells):
        per_cell[i] = np.bincount(labels[r0:r1, c0:c1].ravel(), minlength=count + 1)
    per_cell[:, 0] = 0

    owner = np.full(count + 1, -1, dtype=np.int64)
    for label in range(1, count + 1):
        best = int(per_cell[:, label].argmax())
        if total[label] and per_cell[best, label] >= 0.75 * total[label]:
            owner[label] = best

    whole = owner[labels]
    for i, (r0, r1, c0, c1) in enumerate(cells):
        masks[i] |= whole == i
        # Shared parts: only the pixels inside this cell.
        split = (owner[labels[r0:r1, c0:c1]] == -1) & (labels[r0:r1, c0:c1] > 0)
        masks[i][r0:r1, c0:c1] |= split

    # Specks within a cell are not part of the figure.
    for i, mask in enumerate(masks):
        sub, n = _label(mask)
        if n > 1:
            areas = np.bincount(sub.ravel(), minlength=n + 1)
            areas[0] = 0
            masks[i] = np.isin(sub, np.flatnonzero(areas >= 0.03 * areas.max()))
    return masks


def detect_frames(sheet: Image.Image) -> list[list[DetectedFrame]]:
    """Every figure on the sheet, cleaned and cropped, in rows.

    Rows first, then frames within each row: a sheet is laid out in rows,
    and an empty horizontal band between them is the most reliable thing on
    it. Joining touching figures by connectivity was tried first and failed
    on a real sheet -- a tentacle reaching into the next cell, or a stray
    line across a row boundary, glued whole rows into one "frame".
    """
    full, visible = _visible_mask(sheet)
    h, w = visible.shape

    scale = min(1.0, DETECT_MAX_SIDE / max(h, w))
    small = np.asarray(
        Image.fromarray((visible * 255).astype(np.uint8)).resize(
            (max(1, int(w * scale)), max(1, int(h * scale))), Image.BILINEAR
        )
    ) > 60
    sh, sw = small.shape

    # Rows: bands of the sheet with something in them. A line a couple of
    # pixels tall is not a row of characters.
    # Rows first: the band between two rows of characters is the most
    # reliable thing on a sheet. A band with next to nothing in it -- a stray
    # line, a shadow -- is not a row.
    row_profile = small.sum(axis=1)
    row_spans = _split(row_profile)
    if row_spans:
        heaviest = max(_mass(row_profile, span) for span in row_spans)
        row_spans = [span for span in row_spans if _mass(row_profile, span) >= 0.08 * heaviest]

    grid: list[list[tuple[int, int, int, int]]] = []
    for r0, r1 in row_spans:
        band = small[r0:r1]
        col_profile = band.sum(axis=0)
        col_spans = _split(col_profile)
        if col_spans:
            # A narrow sliver between two figures is part of one of them (a
            # bottle held away from the hand), not a frame: join it to the
            # nearer neighbour rather than dropping the drawing.
            widths = sorted(b - a for a, b in col_spans)
            typical = widths[len(widths) // 2]
            merged: list[list[int]] = []
            for a, b in col_spans:
                if merged and (b - a < 0.35 * typical or merged[-1][1] - merged[-1][0] < 0.35 * typical):
                    merged[-1][1] = b
                else:
                    merged.append([a, b])
            heaviest = max(_mass(col_profile, (a, b)) for a, b in merged)
            col_spans = [(a, b) for a, b in merged if _mass(col_profile, (a, b)) >= 0.08 * heaviest]
        if col_spans:
            grid.append([(r0, r1, c0, c1) for c0, c1 in col_spans])

    cells = [cell for row in grid for cell in row]
    masks = _assign_parts(small, cells)

    result: list[list[DetectedFrame]] = []
    index = 0
    for row in grid:
        detected: list[DetectedFrame] = []
        for _cell in row:
            cell = masks[index]
            index += 1
            ys = np.flatnonzero(cell.any(axis=1))
            xs = np.flatnonzero(cell.any(axis=0))
            if len(ys) == 0:
                continue
            y0, y1 = ys[0], ys[-1] + 1
            x0, x1 = xs[0], xs[-1] + 1

            fx0, fy0 = max(0, int(x0 / scale) - 2), max(0, int(y0 / scale) - 2)
            fx1, fy1 = min(w, int(x1 / scale) + 2), min(h, int(y1 / scale) + 2)
            crop = full.crop((fx0, fy0, fx1, fy1))

            # Only what belongs to this figure: a neighbour's tentacle and
            # stray specks dropped above stay dropped at full resolution too.
            region = (cell[y0:y1, x0:x1] * 255).astype(np.uint8)
            keep = Image.fromarray(region).filter(ImageFilter.MaxFilter(3)).resize(crop.size, Image.NEAREST)
            alpha = np.minimum(np.asarray(crop.getchannel("A")), np.asarray(keep))
            crop.putalpha(Image.fromarray(alpha.astype(np.uint8)))

            cleaned = "none"
            # A frame that sits on its own card (the rest of the sheet was
            # transparent): the card fills the crop and is its border, so it
            # comes off here, frame by frame.
            if not already_transparent(crop):
                cut, changed = cut_out(crop)
                if changed:
                    crop = cut
                    cleaned = cut.info.get("cut_mode", "border")
                else:
                    cleaned = "kept"

            bbox = crop.getchannel("A").point(lambda a: 255 if a > ALPHA_VISIBLE else 0).getbbox()
            if bbox:
                crop = crop.crop(bbox)
            detected.append(DetectedFrame(image=crop, box=(fx0, fy0, fx1, fy1), cleaned=cleaned))
        if detected:
            result.append(detected)

    logger.info("folha importada: %d linha(s), %s quadros", len(result), [len(r) for r in result])
    return result
