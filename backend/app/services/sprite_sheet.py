"""Turning loose pose images into one sprite sheet.

Both the admin's AI studio and scripts/make_spritesheet.py build sheets, and
they have to agree on the layout down to the pixel -- the game slices the
image by dividing it by the grid, so an inconsistency here shows up as a
character jittering between frames. One implementation, used by both.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from math import sqrt
from statistics import median

from PIL import Image, ImageFilter

# Safe texture limit for the GPUs that run OBS. Past this some cards refuse
# the texture outright and the character silently disappears.
MAX_SIDE = 4096
ALPHA_BBOX_THRESHOLD = 16
MIN_NORMALIZE_SCALE = 0.65
MAX_NORMALIZE_SCALE = 2.6


def _content_mask(image: Image.Image) -> Image.Image:
    """A stable silhouette for trimming and scale measurement.

    Generated cutouts sometimes retain one or two distant semi-opaque dots.
    Measuring the raw alpha then treats the whole provider canvas as content,
    which is how one character remained tiny inside an otherwise full cell.
    A tiny morphological opening removes those dots from the *measurement*
    without modifying hair, props or any pixels in the delivered artwork.
    """
    visible = image.getchannel("A").point(
        lambda alpha: 255 if alpha >= ALPHA_BBOX_THRESHOLD else 0
    )
    stable = visible.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    return stable if stable.getbbox() else visible


def _visible_area(image: Image.Image) -> int:
    return max(1, _content_mask(image).histogram()[255])


@dataclass
class SheetLayout:
    """What the admin has to type into the character form for this sheet."""

    png: bytes
    columns: int
    rows: int
    frame_count: int
    frame_width: int
    frame_height: int

    @property
    def width(self) -> int:
        return self.frame_width * self.columns

    @property
    def height(self) -> int:
        return self.frame_height * self.rows


def compose_rows(rows: list[list[Image.Image]]) -> SheetLayout:
    """Lays clips out one per row, every cell the same size.

    The game slices a sheet by dividing it into `columns` x `rows` equal cells,
    so a clip can only be addressed as "row r, first n frames" if every row is
    the same width. The widest clip decides the width and the shorter ones are
    padded with empty cells, which no clip ever plays because each declares how
    many frames it owns.
    """
    rows = [row for row in rows if row]
    if not rows:
        raise ValueError("nenhuma pose para montar")

    columns = max(len(row) for row in rows)
    flat: list[Image.Image | None] = []
    for row in rows:
        flat.extend(row)
        flat.extend([None] * (columns - len(row)))

    return _compose(flat, columns)


def compose_sheet(
    frames: list[Image.Image],
    columns: int = 0,
    cell: tuple[int, int] | None = None,
) -> SheetLayout:
    """Lays the poses out on a grid of identical cells.

    Each pose is trimmed of its surrounding transparency first, so poses that
    came back with different margins still end up at the same scale. Inside its
    cell a pose is centred horizontally and pushed to the bottom: aligning by
    the feet is what keeps the character planted on the floor instead of
    bobbing as the animation plays.
    """
    if not frames:
        raise ValueError("nenhuma pose para montar")
    return _compose(list(frames), columns if columns > 0 else len(frames), cell)


def _compose(
    frames: list[Image.Image | None],
    columns: int,
    cell: tuple[int, int] | None = None,
) -> SheetLayout:
    """The shared grid builder. `None` leaves a cell empty."""
    trimmed: list[Image.Image | None] = []
    for frame in frames:
        if frame is None:
            trimmed.append(None)
            continue
        img = frame.convert("RGBA")
        # getbbox() treats an alpha value of 1 as real content. Image models
        # often leave a haze or a few almost-transparent pixels at the edge;
        # including those makes the whole canvas the bounding box and the
        # actual character looks much smaller in that frame.
        visible = _content_mask(img)
        trimmed.append(img.crop(visible.getbbox() or (0, 0, img.width, img.height)))

    drawn = [f for f in trimmed if f is not None]
    if not drawn:
        raise ValueError("nenhuma pose para montar")

    if cell is None and len(drawn) > 1:
        # Normalise camera zoom by foreground area, not bounding-box height.
        # A crouch is shorter but contains roughly the same amount of character;
        # a genuinely zoomed-out frame is smaller in both dimensions. Height
        # alone confused wide tentacle/arm poses with deliberate small figures.
        visible_areas = [_visible_area(frame) for frame in drawn]
        target_area = float(median(visible_areas))
        normalised: list[Image.Image | None] = []
        for frame in trimmed:
            if frame is None:
                normalised.append(None)
                continue
            visible_area = _visible_area(frame)
            scale = max(
                MIN_NORMALIZE_SCALE,
                min(MAX_NORMALIZE_SCALE, sqrt(target_area / visible_area)),
            )
            if abs(scale - 1.0) < 0.01:
                normalised.append(frame)
            else:
                normalised.append(
                    frame.resize(
                        (
                            max(1, round(frame.width * scale)),
                            max(1, round(frame.height * scale)),
                        ),
                        Image.LANCZOS,
                    )
                )
        trimmed = normalised
        drawn = [frame for frame in trimmed if frame is not None]

    cell_w, cell_h = cell or (max(f.width for f in drawn), max(f.height for f in drawn))
    columns = max(1, columns)
    rows = -(-len(trimmed) // columns)  # ceiling division

    scale = min(1.0, MAX_SIDE / (cell_w * columns), MAX_SIDE / (cell_h * rows))
    if scale < 1.0:
        cell_w, cell_h = max(1, int(cell_w * scale)), max(1, int(cell_h * scale))

    sheet = Image.new("RGBA", (cell_w * columns, cell_h * rows), (0, 0, 0, 0))
    for i, frame in enumerate(trimmed):
        if frame is None:
            continue
        ratio = min(cell_w / frame.width, cell_h / frame.height)
        resized = frame.resize(
            (max(1, int(frame.width * ratio)), max(1, int(frame.height * ratio))),
            Image.LANCZOS,
        )
        col, row = i % columns, i // columns
        x = col * cell_w + (cell_w - resized.width) // 2
        y = row * cell_h + (cell_h - resized.height)
        sheet.paste(resized, (x, y), resized)

    buffer = BytesIO()
    sheet.save(buffer, format="PNG")
    return SheetLayout(
        png=buffer.getvalue(),
        columns=columns,
        rows=rows,
        frame_count=len(drawn),
        frame_width=cell_w,
        frame_height=cell_h,
    )
