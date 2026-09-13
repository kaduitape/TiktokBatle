import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import require_admin
from app.core.config import settings
from app.services import sprite_studio
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


@router.get("/status")
async def studio_status(_: str = Depends(require_admin)):
    """Whether the panel can generate. Deliberately says nothing about the key
    itself -- not even a masked copy -- only that one is present."""
    return {
        "configured": sprite_studio.is_configured(),
        "model": settings.image_model,
        "max_poses": MAX_POSES,
    }


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


@router.post("/generate", response_model=GenerateOut)
async def generate(body: GenerateRequest, _: str = Depends(require_admin)):
    base_image = _read_upload(body.base_image_url) if body.base_image_url else None

    try:
        result = await sprite_studio.generate_artwork(
            description=body.description,
            poses=body.poses,
            base_image=base_image,
            want_hit=body.want_hit,
            want_fire=body.want_fire,
            columns=body.columns,
            size=body.size,
        )
    except SpriteStudioError as exc:
        # The message is written for the admin, so pass it through instead of
        # collapsing it into a generic failure.
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("sprite generation failed")
        raise HTTPException(500, f"Falha ao gerar: {exc}") from exc

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
