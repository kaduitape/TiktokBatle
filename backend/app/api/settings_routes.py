from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Setting

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULTS: dict[str, dict[str, Any]] = {
    "audio_mixer": {
        "music": 30,
        "shots": 80,
        "explosions": 80,
        "alerts": 70,
        "ui": 50,
        "victory": 80,
    }
}


@router.get("/{key}")
async def get_setting(key: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(Setting, key)
    if row:
        return row.value
    return DEFAULTS.get(key, {})


@router.put("/{key}")
async def put_setting(key: str, value: dict[str, Any], db: AsyncSession = Depends(get_db)):
    row = await db.get(Setting, key)
    if row:
        row.value = value
    else:
        row = Setting(key=key, value=value)
        db.add(row)
    await db.commit()
    return value
