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
# Fraction of a frame's own visible height treated as "head and shoulders"
# for horizontal alignment. Narrow enough that a raised arm or a swinging
# tentacle rarely reaches into it, wide enough to survive a hat or big hair.
ANCHOR_BAND = 0.22
# A centroid needs only coarse resolution; shrinking to this width first keeps
# the scan cheap even on a frame the studio generated at 1600x2400.
ANCHOR_THUMB_MAX = 96


def _content_mask(image: Image.Image) -> Image.Image:
    """A stable silhouette for trimming and scale measurement.

    Generated cutouts sometimes retain one or two distant semi-opaque dots.
    Measuring the raw alpha then treats the whole provider canvas as content,
    which is how one character remained tiny inside an otherwise full cell.
    A tiny morphological opening removes those dots from the *measurement*
    without modifying hair, props or any pixels in the delivered artwork.
    """
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] >= 250:
        # No transparency at all: the frame still has the card it was drawn
        # on. Measured by alpha, the whole canvas would count as character,
        # the frame would look huge, and normalisation would shrink the
        # drawing inside it -- the frame that arrived clean then looks
        # bigger than all the others. Measure by distance from the card's
        # colour instead, so at least the size stays honest.
        visible = _differs_from_border(image)
    else:
        visible = alpha.point(lambda a: 255 if a >= ALPHA_BBOX_THRESHOLD else 0)
    stable = visible.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    return stable if stable.getbbox() else visible


def _differs_from_border(image: Image.Image) -> Image.Image:
    """Pixels that are not the border's colour, as a 0/255 mask."""
    from app.services.background_cutout import DEFAULT_TOLERANCE, border_colour
    import numpy as np

    rgb = np.asarray(image.convert("RGB"))
    colour, _agreement = border_colour(rgb)
    distance = np.abs(rgb.astype(np.int16) - colour).max(axis=2)
    return Image.fromarray(((distance > DEFAULT_TOLERANCE) * 255).astype("uint8"), mode="L")


def _visible_area(image: Image.Image) -> int:
    return max(1, _content_mask(image).histogram()[255])


def _horizontal_anchor(image: Image.Image) -> float:
    """Where this frame's body actually sits, in its own pixel columns.

    Centering a cell on the full silhouette's bounding box is what makes an
    animation wobble left and right: a punch, a wave or a bomb toss widens
    the box on one side and drags the whole character sideways with it, even
    though the torso itself never moved. The anchor is instead the centre of
    mass of the top of the figure -- head, hat, shoulders -- which stays
    close to still while limbs swing, so poses line up on the body rather
    than on whatever the silhouette happens to reach that frame.

    Returns the x in ``image``'s own coordinates; ``image.width / 2`` (the
    old bbox-centre behaviour) if the band is empty, which only happens on
    an almost blank frame.
    """
    mask = _content_mask(image)
    band_h = max(1, round(mask.height * ANCHOR_BAND))
    band = mask.crop((0, 0, mask.width, band_h))
    if band.getbbox() is None:
        return image.width / 2

    thumb_w = max(1, min(ANCHOR_THUMB_MAX, band.width))
    thumb_h = max(1, round(band_h * thumb_w / band.width))
    thumb = band.resize((thumb_w, thumb_h))
    pixels = thumb.load()
    total = 0
    weighted = 0.0
    for y in range(thumb_h):
        for x in range(thumb_w):
            if pixels[x, y] >= 128:
                total += 1
                weighted += x
    if total == 0:
        return image.width / 2
    return (weighted / total) / thumb_w * image.width


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

    # An anchor only stops the wobble if every frame actually has room either
    # side of it to be shifted into place. Sizing the cell by the widest
    # frame alone -- the old rule -- can leave that one frame with none: a
    # fully extended arm reaching all the way to the cell's edge has nowhere
    # left to move, so it stays pinned however far off-anchor its silhouette
    # happens to sit, while narrower poses float freely to the true centre.
    # The cell is sized instead so that the anchor's two sides both fit,
    # which costs a little unused margin on a lopsided pose and is what
    # actually keeps the head still frame to frame.
    anchors: dict[int, float] = {}
    if cell is None:
        left_reach = right_reach = 0.0
        for i, frame in enumerate(trimmed):
            if frame is None:
                continue
            anchor_x = _horizontal_anchor(frame)
            anchors[i] = anchor_x
            left_reach = max(left_reach, anchor_x)
            right_reach = max(right_reach, frame.width - anchor_x)
        cell_w = max(1, round(2 * max(left_reach, right_reach)))
        cell_h = max(f.height for f in drawn)
    else:
        cell_w, cell_h = cell
    columns = max(1, columns)
    rows = -(-len(trimmed) // columns)  # ceiling division

    scale = min(1.0, MAX_SIDE / (cell_w * columns), MAX_SIDE / (cell_h * rows))
    if scale < 1.0:
        cell_w, cell_h = max(1, int(cell_w * scale)), max(1, int(cell_h * scale))

    sheet = Image.new("RGBA", (cell_w * columns, cell_h * rows), (0, 0, 0, 0))
    for i, frame in enumerate(trimmed):
        if frame is None:
            continue
        anchor_x = anchors[i] if i in anchors else _horizontal_anchor(frame)
        # Every frame gets the same scale -- the sheet's own downscale -- and
        # is only shrunk further if it does not fit. Fitting each frame to the
        # cell used to blow a crouch up to full height and undo the size
        # normalisation above.
        ratio = min(scale, cell_w / frame.width, cell_h / frame.height)
        resized = frame.resize(
            (max(1, int(frame.width * ratio)), max(1, int(frame.height * ratio))),
            Image.LANCZOS,
        )
        col, row = i % columns, i // columns
        # The anchor keeps the same spot in the cell on every frame; a pose
        # whose limbs happen to reach further left or right than usual still
        # lands with its head where the others' heads are, instead of being
        # nudged over to keep the whole silhouette centred.
        anchor_resized = anchor_x * ratio
        cell_x = round(cell_w / 2 - anchor_resized)
        cell_x = max(0, min(cell_w - resized.width, cell_x))
        x = col * cell_w + cell_x
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


# ---------------------------------------------------------------------------
# One sheet per movement
# ---------------------------------------------------------------------------


@dataclass
class MovementStandard:
    """What every movement of one character must agree on.

    Separate sheets are only interchangeable if the character is the same
    size and in the same place in all of them: the arena swaps sheets when a
    gesture starts, and any difference shows up as the character jumping in
    scale or sliding sideways at that moment. So the cell, and how much of
    it the character fills, are decided once -- by the base movement -- and
    every other movement is fitted to them.
    """

    cell_w: int
    cell_h: int
    #: Median visible area of one frame, in cell pixels.
    target_area: float


def _trimmed(frame: Image.Image) -> Image.Image:
    img = frame.convert("RGBA")
    return img.crop(_content_mask(img).getbbox() or (0, 0, img.width, img.height))


def _to_area(frame: Image.Image, target_area: float) -> Image.Image:
    scale = max(
        MIN_NORMALIZE_SCALE,
        min(MAX_NORMALIZE_SCALE, sqrt(target_area / _visible_area(frame))),
    )
    if abs(scale - 1.0) < 0.01:
        return frame
    return frame.resize(
        (max(1, round(frame.width * scale)), max(1, round(frame.height * scale))), Image.LANCZOS
    )


def _grid(frames: list[Image.Image], anchors: list[float], cell_w: int, cell_h: int) -> SheetLayout:
    """Lay one movement's frames on a grid that stays inside MAX_SIDE.

    Wrapped into rows rather than one long strip, so a 24-frame loop fits a
    texture without shrinking. When even that is too big, the whole grid is
    scaled down; the arena refits the character to the same on-screen height
    whenever it switches sheet, so a smaller cell does not mean a smaller
    character.
    """
    n = len(frames)
    scale = 1.0
    while True:
        cw, ch = max(1, int(cell_w * scale)), max(1, int(cell_h * scale))
        columns = max(1, min(n, MAX_SIDE // cw))
        rows = -(-n // columns)
        if rows * ch <= MAX_SIDE or scale < 0.05:
            break
        scale *= 0.9

    sheet = Image.new("RGBA", (cw * columns, ch * rows), (0, 0, 0, 0))
    for i, (frame, anchor) in enumerate(zip(frames, anchors)):
        # Same scale for every frame (only shrunk if it does not fit), so the
        # character is the same size in every frame of every movement.
        ratio = min(scale, cw / frame.width, ch / frame.height)
        resized = frame.resize(
            (max(1, int(frame.width * ratio)), max(1, int(frame.height * ratio))), Image.LANCZOS
        )
        col, row = i % columns, i // columns
        x = round(cw / 2 - anchor * ratio)
        x = max(0, min(cw - resized.width, x))
        sheet.paste(resized, (col * cw + x, row * ch + (ch - resized.height)), resized)

    buffer = BytesIO()
    sheet.save(buffer, format="PNG")
    return SheetLayout(
        png=buffer.getvalue(),
        columns=columns,
        rows=rows,
        frame_count=n,
        frame_width=cw,
        frame_height=ch,
    )


def compose_movements(
    movements: list[list[Image.Image]],
    standard: MovementStandard | None = None,
) -> tuple[list[SheetLayout], MovementStandard]:
    """One sheet per movement, all of them agreeing on size and position.

    Without a ``standard`` the movements given here set it together (the
    studio and the importer, which produce every movement at once). With one
    -- a movement added later to an existing character -- the new frames are
    fitted to it instead, so the new sheet slots in next to the old ones.
    """
    trimmed = [[_trimmed(f) for f in frames] for frames in movements]
    every = [f for frames in trimmed for f in frames]
    if not every:
        raise ValueError("nenhuma pose para montar")

    target = standard.target_area if standard else float(median(_visible_area(f) for f in every))
    normalised = [[_to_area(f, target) for f in frames] for frames in trimmed]
    anchors = [[_horizontal_anchor(f) for f in frames] for frames in normalised]

    if standard:
        cell_w, cell_h = standard.cell_w, standard.cell_h
    else:
        left = max(a for group in anchors for a in group)
        right = max(f.width - a for frames, group in zip(normalised, anchors) for f, a in zip(frames, group))
        cell_w = max(1, round(2 * max(left, right)))
        cell_h = max(f.height for frames in normalised for f in frames)
        standard = MovementStandard(cell_w=cell_w, cell_h=cell_h, target_area=target)

    sheets = [
        _grid(frames, group, cell_w, cell_h) if frames else None
        for frames, group in zip(normalised, anchors)
    ]
    return sheets, standard


def standard_from_sheet(image: Image.Image, columns: int, rows: int, frame_count: int) -> MovementStandard:
    """Read the standard back out of an existing movement's sheet.

    The base movement's cell is the standard's cell, and its frames' median
    visible area is the size every later movement is fitted to -- both in
    that sheet's own pixels, so a base sheet that had to be shrunk to fit is
    still matched exactly.
    """
    rgba = image.convert("RGBA")
    columns, rows = max(1, columns), max(1, rows)
    cw, ch = rgba.width // columns, rgba.height // rows
    count = frame_count if frame_count > 0 else columns * rows
    areas = []
    for i in range(count):
        col, row = i % columns, i // columns
        cell = rgba.crop((col * cw, row * ch, (col + 1) * cw, (row + 1) * ch))
        if cell.getchannel("A").getbbox():
            areas.append(_visible_area(cell))
    return MovementStandard(cell_w=cw, cell_h=ch, target_area=float(median(areas)) if areas else cw * ch * 0.4)
