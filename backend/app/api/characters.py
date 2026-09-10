import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.models import Character
from app.schemas.schemas import CharacterIn, CharacterOut

router = APIRouter(prefix="/api/characters", tags=["characters"])


@router.get("", response_model=list[CharacterOut])
async def list_characters(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Character))).scalars().all()


@router.post("", response_model=CharacterOut)
async def create_character(body: CharacterIn, db: AsyncSession = Depends(get_db)):
    character = Character(**body.model_dump())
    db.add(character)
    await db.commit()
    await db.refresh(character)
    return character


@router.get("/{character_id}", response_model=CharacterOut)
async def get_character(character_id: str, db: AsyncSession = Depends(get_db)):
    character = await db.get(Character, character_id)
    if not character:
        raise HTTPException(404, "character not found")
    return character


@router.put("/{character_id}", response_model=CharacterOut)
async def update_character(character_id: str, body: CharacterIn, db: AsyncSession = Depends(get_db)):
    character = await db.get(Character, character_id)
    if not character:
        raise HTTPException(404, "character not found")
    for k, v in body.model_dump().items():
        setattr(character, k, v)
    await db.commit()
    await db.refresh(character)
    return character


@router.delete("/{character_id}")
async def delete_character(character_id: str, db: AsyncSession = Depends(get_db)):
    character = await db.get(Character, character_id)
    if not character:
        raise HTTPException(404, "character not found")
    await db.delete(character)
    await db.commit()
    return {"ok": True}


@router.post("/upload")
async def upload_character_asset(file: UploadFile):
    os.makedirs(settings.upload_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".png"
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.upload_dir, filename)
    with open(path, "wb") as f:
        f.write(await file.read())
    return {"url": f"/uploads/{filename}"}
