import json
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger("ws")


class ConnectionManager:
    """Broadcasts game events to every Phaser client watching a given
    battle session. One 'room' per session_id -- an OBS browser source
    just opens ws://.../ws/arena/{session_id} and starts receiving the
    exact same event stream the simulator and the live provider produce."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._rooms[session_id].add(ws)

    def disconnect(self, session_id: str, ws: WebSocket) -> None:
        self._rooms[session_id].discard(ws)
        if not self._rooms[session_id]:
            del self._rooms[session_id]

    async def broadcast(self, session_id: str, message: dict) -> None:
        dead: list[WebSocket] = []
        payload = json.dumps(message)
        for ws in self._rooms.get(session_id, set()):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(session_id, ws)

    def connection_count(self, session_id: str) -> int:
        return len(self._rooms.get(session_id, set()))


connection_manager = ConnectionManager()
