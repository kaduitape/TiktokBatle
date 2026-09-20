import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.auth import verify_token
from app.services.battle_loop import battle_loop
from app.services.state_sync import build_state_sync
from app.ws.admin_channel import admin_channel
from app.ws.connection_manager import connection_manager

router = APIRouter()
logger = logging.getLogger("ws_routes")


@router.websocket("/ws/arena/{session_id}")
async def arena_socket(websocket: WebSocket, session_id: str):
    await connection_manager.connect(session_id, websocket)
    try:
        state = await build_state_sync(session_id)
        if state:
            await websocket.send_json(state)

        # PvP fights and boss bombs run on a server tick -- only while
        # somebody is actually watching this session.
        await battle_loop.maybe_start_for_session(session_id)

        while True:
            # Clients don't need to send anything; this just detects disconnects
            # and tolerates any keepalive pings the client chooses to send.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.disconnect(session_id, websocket)
        if connection_manager.connection_count(session_id) == 0:
            await battle_loop.stop(session_id)


@router.websocket("/ws/admin")
async def admin_socket(websocket: WebSocket, token: str = ""):
    """Live feed for the admin panel: newly discovered gifts and the raw
    event monitor.

    Authenticated, unlike the arena socket. A browser cannot set headers on a
    WebSocket handshake, so the panel passes its existing bearer token as a
    query parameter -- rejected before the socket is accepted, so an
    unauthenticated client never sees a single gift ID.
    """
    try:
        verify_token(token)
    except ValueError:
        # 1008 = policy violation. Closing before accept() keeps the handshake
        # from completing at all.
        await websocket.close(code=1008)
        return

    await admin_channel.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        admin_channel.disconnect(websocket)
