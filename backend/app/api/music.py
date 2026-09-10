import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.models import MusicTrack
from app.schemas.schemas import MusicTrackIn, MusicTrackOut

router = APIRouter(prefix="/api/music", tags=["music"])


@router.get("", response_model=list[MusicTrackOut])
async def list_tracks(db: AsyncSession = Depends(get_db)):
    tracks = (await db.execute(select(MusicTrack))).scalars().all()
    return sorted(tracks, key=lambda t: (t.category, t.order_index))


@router.post("", response_model=MusicTrackOut)
async def create_track(body: MusicTrackIn, db: AsyncSession = Depends(get_db)):
    track = MusicTrack(**body.model_dump())
    db.add(track)
    await db.commit()
    await db.refresh(track)
    return track


@router.delete("/{track_id}")
async def delete_track(track_id: str, db: AsyncSession = Depends(get_db)):
    track = await db.get(MusicTrack, track_id)
    if not track:
        raise HTTPException(404, "track not found")
    await db.delete(track)
    await db.commit()
    return {"ok": True}


@router.post("/upload")
async def upload_track(file: UploadFile):
    os.makedirs(settings.upload_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".mp3"
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.upload_dir, filename)
    with open(path, "wb") as f:
        f.write(await file.read())
    return {"url": f"/uploads/{filename}"}
