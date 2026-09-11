import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import require_admin
from app.providers.tiktok_provider import tiktok_provider

router = APIRouter(prefix="/api/live", tags=["live"])
logger = logging.getLogger("live_api")


class ConnectRequest(BaseModel):
    tiktok_username: str


@router.post("/{session_id}/connect")
async def connect_live(session_id: str, body: ConnectRequest, _: str = Depends(require_admin)):
    """Phase 7 of the spec's MVP ordering: only meant to be used once the
    simulator has already proven the pipeline end-to-end. Runs the
    TikTokLive client in a background task since it holds its own
    connection open for the life of the stream."""
    if tiktok_provider.is_connected(session_id):
        raise HTTPException(400, "already connected for this session")

    async def _run():
        try:
            await tiktok_provider.start(session_id, tiktok_username=body.tiktok_username)
        except Exception:
            logger.exception("tiktok live connection for session=%s ended", session_id)

    asyncio.create_task(_run())
    return {"ok": True, "connecting_to": body.tiktok_username}


@router.post("/{session_id}/disconnect")
async def disconnect_live(session_id: str, _: str = Depends(require_admin)):
    await tiktok_provider.stop(session_id)
    return {"ok": True}


@router.get("/{session_id}/status")
async def live_status(session_id: str, _: str = Depends(require_admin)):
    return {"connected": tiktok_provider.is_connected(session_id)}
