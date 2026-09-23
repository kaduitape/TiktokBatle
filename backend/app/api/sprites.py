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
from app.models.models import SpriteModel
from app.schemas.schemas import SpriteModelIn, SpriteModelOut
from app.services import secret_store, sprite_studio
from app.services.image_providers import ImageProviderError
from app.services.sprite_studio import SpriteStudioError

router = APIRouter(prefix="/api/sprites", tags=["sprites"])
logger = logging.getLogger("sprites")

# Enough poses to read as an animation without burning credits by accident.
MAX_POSES = 8


class GenerateRequest(BaseModel):
    description: str = ""
    poses: list[str] = Field(default_factory=list, max_length=MAX_POSES)
    # An /uploads path for a caricature the admin already has. When present it
    # becomes the character's neutral frame and the reference for every edit,
    # so the likeness is theirs instead of the model's invention.
    base_image_url: str | None = None
    want_hit: bool = False
    want_fire: bool = False
    columns: int = 0
    size: str = sprite_studio.DEFAULT_SIZE


class GenerateOut(BaseModel):
    url: str | None = None
    columns: int = 0
    rows: int = 1
    frame_count: int = 0
    frame_width: int = 0
    frame_height: int = 0
    hit_url: str | None = None
    fire_url: str | None = None


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
            poses=body.poses,
            base_image=base_image,
            want_hit=body.want_hit,
            want_fire=body.want_fire,
            columns=body.columns,
            size=body.size,
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
    if result.hit:
        out.hit_url = _save_png(result.hit)
    if result.fire:
        out.fire_url = _save_png(result.fire)
    return out


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
        description=body.description,
        poses_json=list(body.poses),
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return _model_out(model)


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
