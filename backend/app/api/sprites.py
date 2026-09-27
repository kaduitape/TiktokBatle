import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.core.config import settings
from app.core.database import get_db
from app.models.models import GesturePreset, SpriteModel
from app.schemas.schemas import (
    GesturePresetIn,
    GesturePresetOut,
    SpriteModelIn,
    SpriteModelOut,
)
from app.services import secret_store, sprite_studio
from app.services.image_providers import ImageProviderError
from app.services.sprite_studio import SpriteStudioError

router = APIRouter(prefix="/api/sprites", tags=["sprites"])
logger = logging.getLogger("sprites")

# Enough poses to read as an animation without burning credits by accident.
MAX_POSES = 16

# Gestures are extra rows, each its own handful of calls, so they are capped
# separately -- a run with six gestures of four frames is twenty-four images.
MAX_GESTURES = 6
MAX_GESTURE_POSES = 12


class GestureIn(BaseModel):
    """One short movement the character does between loops of the base one."""

    name: str = Field(min_length=1, max_length=40)
    poses: list[str] = Field(default_factory=list, max_length=MAX_GESTURE_POSES)
    #: Fraction of its own height the character rises while this plays, so a
    #: hop actually leaves the floor -- the sheet stands every frame on its feet.
    lift: float = Field(default=0.0, ge=0.0, le=1.0)
    weight: float = Field(default=1.0, gt=0.0, le=10.0)
    fps: int = Field(default=0, ge=0, le=60)


class GenerateRequest(BaseModel):
    description: str = ""
    adjustment_prompt: str = Field(default="", max_length=2000)
    poses: list[str] = Field(default_factory=list, max_length=MAX_POSES)
    # An /uploads path for a caricature the admin already has. When present it
    # becomes the character's neutral frame and the reference for every edit,
    # so the likeness is theirs instead of the model's invention.
    base_image_url: str | None = None
    want_hit: bool = False
    want_fire: bool = False
    columns: int = 0
    size: str = sprite_studio.DEFAULT_SIZE
    gestures: list[GestureIn] = Field(default_factory=list, max_length=MAX_GESTURES)


class GenerateOut(BaseModel):
    url: str | None = None
    columns: int = 0
    rows: int = 1
    frame_count: int = 0
    frame_width: int = 0
    frame_height: int = 0
    hit_url: str | None = None
    fire_url: str | None = None
    #: What each row of the sheet is. Empty means the whole grid is one loop.
    clips: list[dict] = Field(default_factory=list)
    #: Frames whose background did not come off cleanly, for the panel.
    warnings: list[str] = Field(default_factory=list)
    #: One sheet per movement (base, each gesture, hit, fire), all fitted to
    #: the same size -- what the arena uses when present.
    movements: list[dict] = Field(default_factory=list)


class KeyIn(BaseModel):
    """Saving a key. The key itself is the point, so it is required."""

    key: str = Field(min_length=8, max_length=400)
    # Which service the key belongs to. Omitted means the one in use.
    provider: str | None = None


class KeyTestIn(BaseModel):
    """Testing a key, which has two legitimate shapes.

    With a key: check one before saving it. Without: check the one already
    saved. Reusing KeyIn here made the second form a 422 -- the panel's
    "Testar" button on an empty field sent no key and was rejected before it
    ever reached the provider.
    """

    key: str | None = Field(default=None, max_length=400)
    provider: str | None = None


@router.get("/status")
async def studio_status(_: str = Depends(require_admin)):
    """Which service is drawing, whether it can, and the state of every key.

    A key is only ever described -- where it came from and its last four
    characters -- never returned.
    """
    provider = await sprite_studio.resolve_provider()
    key, source = await sprite_studio.resolve_key(provider)

    providers = []
    for entry in sprite_studio.PROVIDER_CATALOG():
        entry_key, entry_source = await sprite_studio.resolve_key(entry["id"])
        providers.append(
            {
                **entry,
                "configured": bool(entry_key),
                "source": entry_source,
                "masked": secret_store.mask(entry_key),
                "model": _model_of(entry["id"]),
            }
        )

    return {
        "configured": bool(key),
        "source": source,
        "masked": secret_store.mask(key),
        "provider": provider,
        "model": _model_of(provider),
        "providers": providers,
        "max_poses": MAX_POSES,
        "max_gestures": MAX_GESTURES,
        "max_gesture_poses": MAX_GESTURE_POSES,
    }


def _model_of(provider: str) -> str:
    return {
        "openai": settings.image_model,
        "gemini": settings.gemini_image_model,
        "aisa": settings.aisa_image_model,
    }.get(provider, settings.image_model)


class ProviderIn(BaseModel):
    provider: str


@router.put("/provider")
async def choose_provider(
    body: ProviderIn, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    """Switches which service draws. Keys are kept per provider, so going back
    to a previous one does not mean pasting its key again."""
    try:
        name = await sprite_studio.set_provider(db, body.provider)
    except ImageProviderError as exc:
        raise HTTPException(400, str(exc)) from exc
    key, source = await sprite_studio.resolve_key(name)
    return {"provider": name, "configured": bool(key), "source": source}


@router.put("/key")
async def save_key(body: KeyIn, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    """Stores the key pasted in the panel, under the provider it belongs to.

    It is written to the database as given -- the app has no secret storage of
    its own -- so a database dump carries it.
    """
    provider = (body.provider or await sprite_studio.resolve_provider()).lower()
    await secret_store.set_value(db, secret_store.image_key_name(provider), body.key.strip())
    key, source = await sprite_studio.resolve_key(provider)
    return {
        "provider": provider,
        "configured": bool(key),
        "source": source,
        "masked": secret_store.mask(key),
    }


@router.delete("/key")
async def delete_key(
    provider: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Removes the saved key for a provider. A key in the server's environment,
    if there is one, takes over again."""
    name = (provider or await sprite_studio.resolve_provider()).lower()
    await secret_store.clear(db, secret_store.image_key_name(name))
    key, source = await sprite_studio.resolve_key(name)
    return {
        "provider": name,
        "configured": bool(key),
        "source": source,
        "masked": secret_store.mask(key),
    }


@router.post("/key/test")
async def test_key(body: KeyTestIn | None = None, _: str = Depends(require_admin)):
    """Confirms a key works before anyone spends credits finding out it does
    not. Pass a key to check one before saving, or none to check the saved one."""
    candidate = (body.key or "").strip() if body else ""
    try:
        message = await sprite_studio.verify_key(
            candidate or None,
            body.provider if body else None,
        )
    except ImageProviderError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "message": message}


def _read_upload(url: str) -> bytes:
    """Loads a previously uploaded file by its /uploads path. The name is
    rebuilt from the basename alone so a crafted path cannot walk out of the
    uploads directory."""
    name = os.path.basename(url.strip())
    if not name or name in (".", ".."):
        raise HTTPException(400, "Caminho da imagem base inválido.")
    path = os.path.join(settings.upload_dir, name)
    if not os.path.isfile(path):
        raise HTTPException(400, "A imagem base enviada não foi encontrada no servidor.")
    with open(path, "rb") as f:
        return f.read()


def _save_png(data: bytes) -> str:
    os.makedirs(settings.upload_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    with open(os.path.join(settings.upload_dir, filename), "wb") as f:
        f.write(data)
    return f"/uploads/{filename}"


@dataclass
class _Job:
    """One generation run, tracked while it happens.

    Generation makes a separate call to the image provider for every frame and
    easily runs past a minute. Held open as a single HTTP request, that dies at
    whatever proxy sits in front of the app -- Cloudflare gives up at 100
    seconds and answers 504 -- while the work carries on invisibly behind it.
    So the request only starts the job and the panel asks how it is going.

    Kept in memory on purpose: a restart cancels everything anyway, and a job
    whose task is gone has nothing to report.
    """

    id: str
    status: str = "running"  # running|done|error
    done: int = 0
    total: int = 0
    label: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None


_JOBS: dict[str, _Job] = {}
# Long enough to survive a panel left on another tab, short enough that a busy
# day does not accumulate finished jobs forever.
_JOB_TTL_SECONDS = 30 * 60


def _forget_old_jobs() -> None:
    now = time.time()
    for job_id, job in list(_JOBS.items()):
        if job.finished_at and (now - job.finished_at) > _JOB_TTL_SECONDS:
            _JOBS.pop(job_id, None)


async def _run_job(job: _Job, body: GenerateRequest, base_image: bytes | None) -> None:
    def progress(done: int, total: int, label: str) -> None:
        job.done, job.total, job.label = done, total, label

    try:
        result = await sprite_studio.generate_artwork(
            description=body.description,
            adjustment_prompt=body.adjustment_prompt,
            poses=body.poses,
            base_image=base_image,
            want_hit=body.want_hit,
            want_fire=body.want_fire,
            columns=body.columns,
            size=body.size,
            gestures=[
                sprite_studio.Gesture(
                    name=g.name,
                    poses=list(g.poses),
                    lift=g.lift,
                    weight=g.weight,
                    fps=g.fps,
                )
                for g in body.gestures
            ],
            on_progress=progress,
        )
        job.result = _to_out(result).model_dump()
        job.status = "done"
    except ImageProviderError as exc:
        # Written for the admin, so pass it through rather than collapsing it
        # into a generic failure.
        job.status, job.error = "error", str(exc)
    except asyncio.CancelledError:
        job.status, job.error = "error", "A geração foi interrompida."
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("sprite generation failed")
        job.status, job.error = "error", f"Falha ao gerar: {exc}"
    finally:
        job.finished_at = time.time()


class JobOut(BaseModel):
    job_id: str
    status: str
    done: int = 0
    total: int = 0
    label: str = ""
    result: GenerateOut | None = None
    error: str | None = None


@router.post("/generate", response_model=JobOut, status_code=202)
async def generate(body: GenerateRequest, _: str = Depends(require_admin)):
    """Starts a generation and returns immediately.

    Poll /api/sprites/jobs/{job_id} for progress and the finished art.
    """
    base_image = _read_upload(body.base_image_url) if body.base_image_url else None

    _forget_old_jobs()
    job = _Job(id=uuid.uuid4().hex)
    _JOBS[job.id] = job
    task = asyncio.create_task(_run_job(job, body, base_image))
    # Without a reference the loop may garbage-collect the task mid-run.
    job_tasks.add(task)
    task.add_done_callback(job_tasks.discard)

    return JobOut(job_id=job.id, status=job.status, done=0, total=0, label="começando")


job_tasks: set[asyncio.Task] = set()


@router.get("/jobs/{job_id}", response_model=JobOut)
async def job_status(job_id: str, _: str = Depends(require_admin)):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(
            404,
            "Esta geração não existe mais. Se o servidor reiniciou, comece de novo.",
        )
    return JobOut(
        job_id=job.id,
        status=job.status,
        done=job.done,
        total=job.total,
        label=job.label,
        result=GenerateOut(**job.result) if job.result else None,
        error=job.error,
    )


def _movement_record(name, kind, layout, fps=0, weight=1.0, lift=0.0) -> dict:
    return {
        "name": name,
        "kind": kind,
        "image_url": _save_png(layout.png),
        "columns": layout.columns,
        "rows": layout.rows,
        "frames": layout.frame_count,
        "frame_width": layout.frame_width,
        "frame_height": layout.frame_height,
        "fps": int(fps or 0),
        "weight": float(weight or 1.0),
        "lift": float(lift or 0.0),
    }


def _save_movements(movement_frames: list[tuple]) -> list[dict]:
    """Every movement on its own sheet, fitted together so they match."""
    from app.services.sprite_sheet import compose_movements

    usable = [m for m in movement_frames if m[2]]
    if not usable:
        return []
    sheets, _standard = compose_movements([m[2] for m in usable])
    return [
        _movement_record(name, kind, sheet, fps, weight, lift)
        for (name, kind, _frames, fps, weight, lift), sheet in zip(usable, sheets)
    ]


def _to_out(result) -> GenerateOut:
    out = GenerateOut()
    if result.sheet:
        out.url = _save_png(result.sheet.png)
        out.frame_width = result.sheet.frame_width
        out.frame_height = result.sheet.frame_height
        if result.sheet.frame_count < 2:
            # A single frame is not an animation. Reporting 0 columns makes the
            # panel apply it as a plain still, which is what an admin who
            # uploaded a caricature and asked only for reaction art wants.
            out.columns, out.rows, out.frame_count = 0, 1, 1
        else:
            out.columns = result.sheet.columns
            out.rows = result.sheet.rows
            out.frame_count = result.sheet.frame_count
        out.clips = list(result.clips)
        if out.columns == 0:
            # Applied as a plain still: there is nothing to slice, so the clip
            # list would only describe a grid the game is not going to read.
            out.clips = []
    out.warnings = list(getattr(result, "warnings", []) or [])
    out.movements = _save_movements(getattr(result, "movement_frames", []) or [])
    if result.hit:
        out.hit_url = _save_png(result.hit)
    if result.fire:
        out.fire_url = _save_png(result.fire)
    return out


# ---------------------------------------------------------------------------
# Importing a sheet the admin already has
# ---------------------------------------------------------------------------


class ImportRowIn(BaseModel):
    """What one detected row is for.

    ``base`` rows are the loop -- several of them are joined in order, which
    is what a single long animation wrapped over several rows needs.
    ``gesture`` rows play now and then; ``hit`` and ``fire`` take the row's
    first frame as the reaction still; ``ignore`` leaves the row out.
    """

    role: str = Field(pattern="^(base|gesture|hit|fire|ignore)$")
    name: str = Field(default="", max_length=40)


class ImportIn(BaseModel):
    image_url: str
    #: One entry per detected row, in order. Omitted: a sensible guess.
    rows: list[ImportRowIn] | None = None


class ImportRowOut(BaseModel):
    index: int
    frames: int
    role: str
    name: str
    #: A small strip of the row's frames, so the panel can show what it is.
    preview: str


class ImportOut(GenerateOut):
    detected: list[ImportRowOut] = Field(default_factory=list)


def _guess_roles(counts: list[int]) -> list[ImportRowIn]:
    """A first answer the admin can correct.

    Rows of equal length (the last one possibly shorter) read as one
    animation wrapped over several lines -- all of it is the loop. Otherwise
    the longest row is the loop and the rest are gestures.
    """
    if not counts:
        return []
    full = counts[:-1] if len(counts) > 1 else counts
    if len(set(full)) == 1 and counts[-1] <= full[0]:
        return [ImportRowIn(role="base") for _ in counts]
    base = counts.index(max(counts))
    roles, n = [], 0
    for i in range(len(counts)):
        if i == base:
            roles.append(ImportRowIn(role="base"))
        else:
            n += 1
            roles.append(ImportRowIn(role="gesture", name=f"gesto_{n}"))
    return roles


def _row_preview(frames, height: int = 64) -> str:
    """The row's frames side by side, as a small inline PNG."""
    import base64
    from io import BytesIO

    from PIL import Image

    thumbs = []
    for f in frames:
        img = f.image
        ratio = height / max(1, img.height)
        thumbs.append(img.resize((max(1, int(img.width * ratio)), height), Image.LANCZOS))
    strip = Image.new("RGBA", (sum(t.width for t in thumbs) + 6 * len(thumbs), height), (0, 0, 0, 0))
    x = 0
    for t in thumbs:
        strip.alpha_composite(t, (x, 0))
        x += t.width + 6
    buffer = BytesIO()
    strip.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _build_import(image_bytes: bytes, requested: list[ImportRowIn] | None):
    """The CPU-heavy part, run off the event loop."""
    from io import BytesIO

    from PIL import Image

    from app.services.sprite_import import detect_frames
    from app.services.sprite_studio import Gesture, _as_png, _lay_out

    try:
        sheet = Image.open(BytesIO(image_bytes))
        sheet.load()
    except Exception as exc:  # noqa: BLE001 - anything unreadable is the same problem
        raise HTTPException(400, "Não consegui ler a imagem enviada.") from exc

    rows = detect_frames(sheet)
    if not rows:
        raise HTTPException(
            400,
            "Não encontrei nenhum personagem na imagem. Ela precisa ter fundo transparente "
            "ou um fundo liso de uma cor só.",
        )

    counts = [len(r) for r in rows]
    roles = list(requested or _guess_roles(counts))
    # A request made against an earlier detection may not line up: fill or
    # trim rather than fail.
    guess = _guess_roles(counts)
    roles = (roles + guess[len(roles):])[: len(rows)]

    base: list = []
    gestures: list = []
    gesture_rows: list = []
    hit = fire = None
    # A reaction row of several frames is an animation, not a still: it keeps
    # every frame as its own movement (the first is still the hit/fire image).
    reactions: list[tuple] = []
    used = 0
    for row, role in zip(rows, roles):
        images = [f.image for f in row]
        if role.role == "base":
            base += images
        elif role.role == "gesture":
            used += 1
            name = (role.name or f"gesto_{used}").strip().replace(" ", "_")
            gestures.append(Gesture(name=name, poses=[""] * len(images), weight=2.0))
            gesture_rows.append(images)
        elif role.role == "hit" and hit is None:
            hit = _as_png(images[0])
            reactions.append(("hit", "hit", images, 0, 1.0, 0.0))
        elif role.role == "fire" and fire is None:
            fire = _as_png(images[0])
            reactions.append(("fire", "fire", images, 0, 1.0, 0.0))

    if not base:
        # Nothing marked as the loop: the first row that is not a still is.
        for i, role in enumerate(roles):
            if role.role == "gesture":
                base = gesture_rows.pop(0)
                gestures.pop(0)
                roles[i] = ImportRowIn(role="base")
                break
    if not base:
        raise HTTPException(400, "Marque pelo menos uma linha como movimento base.")

    result = _lay_out(base, gestures, gesture_rows, 0, hit, fire)
    result.movement_frames = [m for m in result.movement_frames if m[1] not in ("hit", "fire")] + reactions
    kept = [
        f"linha {ri + 1} quadro {fi + 1}"
        for ri, row in enumerate(rows)
        for fi, frame in enumerate(row)
        if frame.cleaned == "kept"
    ]
    if kept:
        result.warnings = [
            "Não consegui tirar o fundo de: " + ", ".join(kept) + " (não era uma cor lisa). "
            "Use uma imagem com fundo transparente ou de uma cor só."
        ]

    detected = [
        ImportRowOut(
            index=i,
            frames=len(row),
            role=role.role,
            name=role.name,
            preview=_row_preview(row),
        )
        for i, (row, role) in enumerate(zip(rows, roles))
    ]
    return result, detected


@router.post("/import", response_model=ImportOut)
async def import_sheet(body: ImportIn, _: str = Depends(require_admin)):
    """Turns a sheet made elsewhere into a clean, playable one.

    The grid is found, not asked for: each figure on the image is a frame,
    figures in the same band are a row. Each frame is cleaned on its own,
    then the whole set goes through the same composer the AI studio uses --
    equal cells, sizes evened out, heads lined up.
    """
    from starlette.concurrency import run_in_threadpool

    image_bytes = _read_upload(body.image_url)
    result, detected = await run_in_threadpool(_build_import, image_bytes, body.rows)
    out = _to_out(result)
    return ImportOut(**out.model_dump(), detected=detected)


class MovementReference(BaseModel):
    """The character's base movement, which a new movement must match."""

    image_url: str
    columns: int = Field(ge=1)
    rows: int = Field(ge=1)
    frames: int = Field(default=0, ge=0)


class MovementBuildIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    kind: str = Field(pattern="^(idle|gesture|hit|fire)$")
    #: One image = a sheet, whose frames are found; several = one frame each,
    #: in the order given.
    image_urls: list[str] = Field(min_length=1, max_length=120)
    fps: int = Field(default=0, ge=0, le=60)
    weight: float = Field(default=1.0, gt=0, le=10)
    lift: float = Field(default=0.0, ge=0, le=1)
    #: Omitted for the first (base) movement: it sets the standard.
    reference: MovementReference | None = None


def _build_movement(body: MovementBuildIn) -> tuple[dict, list[str]]:
    from io import BytesIO

    from PIL import Image

    from app.services.background_cutout import already_transparent, cut_out
    from app.services.sprite_import import detect_frames
    from app.services.sprite_sheet import compose_movements, standard_from_sheet

    def load(url: str) -> Image.Image:
        try:
            img = Image.open(BytesIO(_read_upload(url)))
            img.load()
            return img.convert("RGBA")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Não consegui ler a imagem {os.path.basename(url)}.") from exc

    warnings: list[str] = []
    if len(body.image_urls) == 1:
        rows = detect_frames(load(body.image_urls[0]))
        frames = [f.image for row in rows for f in row]
        kept = sum(1 for row in rows for f in row if f.cleaned == "kept")
    else:
        frames, kept = [], 0
        for url in body.image_urls:
            img = load(url)
            if not already_transparent(img):
                cleaned, changed = cut_out(img)
                if changed:
                    img = cleaned
                else:
                    kept += 1
            frames.append(img)
    if not frames:
        raise HTTPException(400, "Não encontrei nenhum quadro nessa imagem.")
    if kept:
        warnings.append(
            f"{kept} quadro(s) ficaram com fundo (não era uma cor lisa). "
            "Use PNG com fundo transparente ou de uma cor só."
        )

    standard = None
    if body.reference:
        ref = body.reference
        standard = standard_from_sheet(load(ref.image_url), ref.columns, ref.rows, ref.frames)
    (sheet,), _ = compose_movements([frames], standard)
    record = _movement_record(body.name.strip(), body.kind, sheet, body.fps, body.weight, body.lift)
    return record, warnings


@router.post("/movements/build")
async def build_movement(body: MovementBuildIn, _: str = Depends(require_admin)):
    """One movement, one sheet, as many frames as you have.

    Frames come from a sheet (found automatically) or from separate files,
    one per frame. A movement added to an existing character is fitted to
    its base movement, so switching between them does not change the
    character's size or position.
    """
    from starlette.concurrency import run_in_threadpool

    record, warnings = await run_in_threadpool(_build_movement, body)
    return {"movement": record, "warnings": warnings}


# ---------------------------------------------------------------------------
# Saved models: a finished animated character, kept to be reused
# ---------------------------------------------------------------------------


def _model_out(model: SpriteModel) -> SpriteModelOut:
    return SpriteModelOut(
        id=model.id,
        name=model.name,
        image_url=model.image_url,
        sprite_columns=model.sprite_columns,
        sprite_rows=model.sprite_rows,
        sprite_frame_count=model.sprite_frame_count,
        sprite_fps=model.sprite_fps,
        hit_image_url=model.hit_image_url,
        fire_image_url=model.fire_image_url,
        sprite_clips=list(model.sprite_clips or []),
        sprite_sounds=dict(model.sprite_sounds or {}),
        sprite_movements=list(model.sprite_movements or []),
        description=model.description,
        poses=list(model.poses_json or []),
        created_at=model.created_at,
    )


@router.get("/models", response_model=list[SpriteModelOut])
async def list_models(db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    models = (
        (await db.execute(select(SpriteModel).order_by(SpriteModel.created_at.desc())))
        .scalars()
        .all()
    )
    return [_model_out(m) for m in models]


@router.post("/models", response_model=SpriteModelOut)
async def save_model(
    body: SpriteModelIn, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    """Keeps a generated sheet so it can be applied to any character later.

    The art files are already on disk under /uploads; this only records which
    ones belong together and how the sheet is sliced.
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Dê um nome ao modelo.")
    if not (body.image_url or body.hit_image_url or body.fire_image_url):
        raise HTTPException(400, "Não há nenhuma imagem para salvar neste modelo.")

    existing = (
        await db.execute(select(SpriteModel).where(SpriteModel.name == name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f'Já existe um modelo chamado "{name}".')

    model = SpriteModel(
        name=name,
        image_url=body.image_url,
        sprite_columns=body.sprite_columns,
        sprite_rows=body.sprite_rows,
        sprite_frame_count=body.sprite_frame_count,
        sprite_fps=body.sprite_fps,
        hit_image_url=body.hit_image_url,
        fire_image_url=body.fire_image_url,
        sprite_clips=list(body.sprite_clips),
        sprite_sounds=dict(body.sprite_sounds),
        sprite_movements=list(body.sprite_movements),
        description=body.description,
        poses_json=list(body.poses),
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return _model_out(model)


class SheetSwapIn(BaseModel):
    """A sheet redrawn by hand, put back in place of the generated one.

    Only the art and how it is sliced can change. The clip list stays as it
    was, because the point of editing the PNG outside is to touch up the
    drawing -- the rows still mean what they meant.
    """

    image_url: str
    sprite_columns: int = Field(ge=0, le=64)
    sprite_rows: int = Field(ge=1, le=64)
    sprite_frame_count: int = Field(default=0, ge=0)


@router.put("/models/{model_id}/sheet", response_model=SpriteModelOut)
async def replace_model_sheet(
    model_id: str,
    body: SheetSwapIn,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Swaps a saved model's sheet for an edited one.

    Characters already built from the model keep pointing at their own file,
    so this changes the model only -- applying it again is what carries the
    new drawing over to a character.
    """
    model = await db.get(SpriteModel, model_id)
    if model is None:
        raise HTTPException(404, "modelo não encontrado")
    # The file has to be one of ours: the same basename-only rule the rest of
    # the uploads path uses, so a crafted value cannot point anywhere else.
    _read_upload(body.image_url)

    model.image_url = body.image_url
    model.sprite_columns = body.sprite_columns
    model.sprite_rows = body.sprite_rows
    model.sprite_frame_count = body.sprite_frame_count
    await db.commit()
    await db.refresh(model)
    return _model_out(model)


# ---------------------------------------------------------------------------
# Saved gestures: a movement the admin wrote, kept to be used again
# ---------------------------------------------------------------------------


def _preset_out(row: GesturePreset) -> GesturePresetOut:
    return GesturePresetOut(
        id=row.id,
        name=row.name,
        label=row.label or row.name,
        poses=list(row.poses_json or []),
        fps=row.fps or 0,
        weight=row.weight or 1.0,
        lift=row.lift or 0.0,
        created_at=row.created_at,
    )


@router.get("/gestures", response_model=list[GesturePresetOut])
async def list_gestures(db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    rows = (
        (await db.execute(select(GesturePreset).order_by(GesturePreset.created_at.desc())))
        .scalars()
        .all()
    )
    return [_preset_out(r) for r in rows]


@router.post("/gestures", response_model=GesturePresetOut)
async def save_gesture(
    body: GesturePresetIn, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    """Keeps a hand-written gesture. Saving the same name again replaces it,
    which is what editing one and pressing save is meant to do."""
    name = body.name.strip()
    poses = [p.strip() for p in body.poses if p.strip()]
    if not name:
        raise HTTPException(400, "Dê um nome ao gesto.")
    if not poses:
        raise HTTPException(400, "Escreva pelo menos uma pose para o gesto.")

    row = (
        await db.execute(select(GesturePreset).where(GesturePreset.name == name))
    ).scalar_one_or_none()
    if row is None:
        row = GesturePreset(name=name)
        db.add(row)
    row.label = body.label.strip() or name
    row.poses_json = poses
    row.fps = body.fps
    row.weight = body.weight
    row.lift = body.lift
    await db.commit()
    await db.refresh(row)
    return _preset_out(row)


@router.delete("/gestures/{gesture_id}")
async def delete_gesture(
    gesture_id: str, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    """Forgets the gesture. Sheets already generated with it are untouched:
    the movement is drawn into their rows, not looked up here."""
    row = await db.get(GesturePreset, gesture_id)
    if row is None:
        raise HTTPException(404, "gesto não encontrado")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: str, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    """Forgets the model. The characters already built from it keep their art:
    they point at the same files, which are not touched here."""
    model = await db.get(SpriteModel, model_id)
    if model is None:
        raise HTTPException(404, "modelo não encontrado")
    await db.delete(model)
    await db.commit()
    return {"ok": True}
