"""Turning loose pose images into one sprite sheet.

Both the admin's AI studio and scripts/make_spritesheet.py build sheets, and
they have to agree on the layout down to the pixel -- the game slices the
image by dividing it by the grid, so an inconsistency here shows up as a
character jittering between frames. One implementation, used by both.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image

# Safe texture limit for the GPUs that run OBS. Past this some cards refuse
# the texture outright and the character silently disappears.
MAX_SIDE = 4096


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

    trimmed = []
    for frame in frames:
        img = frame.convert("RGBA")
        trimmed.append(img.crop(img.getbbox() or (0, 0, img.width, img.height)))

    cell_w, cell_h = cell or (max(f.width for f in trimmed), max(f.height for f in trimmed))
    columns = columns if columns > 0 else len(trimmed)
    rows = -(-len(trimmed) // columns)  # ceiling division

    scale = min(1.0, MAX_SIDE / (cell_w * columns), MAX_SIDE / (cell_h * rows))
    if scale < 1.0:
        cell_w, cell_h = max(1, int(cell_w * scale)), max(1, int(cell_h * scale))

    sheet = Image.new("RGBA", (cell_w * columns, cell_h * rows), (0, 0, 0, 0))
    for i, frame in enumerate(trimmed):
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
        frame_count=len(trimmed),
        frame_width=cell_w,
        frame_height=cell_h,
    )
