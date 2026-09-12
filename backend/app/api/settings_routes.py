from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.core.database import get_db
from app.models.models import Setting
from app.services.settings_service import settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/{key}")
async def get_setting(key: str, db: AsyncSession = Depends(get_db)):
    return await settings_service.get(db, key)


@router.put("/{key}")
async def put_setting(
    key: str, value: dict[str, Any], db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)
):
    row = await db.get(Setting, key)
    if row:
        row.value = value
    else:
        row = Setting(key=key, value=value)
        db.add(row)
    await db.commit()
    settings_service.invalidate(key)
    return value
