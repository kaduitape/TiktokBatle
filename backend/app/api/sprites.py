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


class GenerateSheetRequest(BaseModel):
    description: str = Field(min_length=3)
    poses: list[str] = Field(min_length=1, max_length=MAX_POSES)
    columns: int = 0
    size: str = sprite_studio.DEFAULT_SIZE


class SheetOut(BaseModel):
    url: str
    columns: int
    rows: int
    frame_count: int
    frame_width: int
    frame_height: int


@router.get("/status")
async def studio_status(_: str = Depends(require_admin)):
    """Whether the panel can generate. Deliberately says nothing about the key
    itself -- not even a masked copy -- only that one is present."""
    return {
        "configured": sprite_studio.is_configured(),
        "model": settings.image_model,
        "max_poses": MAX_POSES,
    }


@router.post("/generate", response_model=SheetOut)
async def generate_sheet(body: GenerateSheetRequest, _: str = Depends(require_admin)):
    try:
        layout = await sprite_studio.generate_sheet(
            description=body.description,
            poses=body.poses,
            columns=body.columns,
            size=body.size,
        )
    except SpriteStudioError as exc:
        # The message is written for the admin, so pass it through instead of
        # collapsing it into a generic failure.
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("sprite generation failed")
        raise HTTPException(500, f"Falha ao gerar a folha: {exc}") from exc

    os.makedirs(settings.upload_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    with open(os.path.join(settings.upload_dir, filename), "wb") as f:
        f.write(layout.png)

    return SheetOut(
        url=f"/uploads/{filename}",
        columns=layout.columns,
        rows=layout.rows,
        frame_count=layout.frame_count,
        frame_width=layout.frame_width,
        frame_height=layout.frame_height,
    )
