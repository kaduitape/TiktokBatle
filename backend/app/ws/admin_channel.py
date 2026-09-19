"""The admin panel's own broadcast channel.

Deliberately separate from :mod:`app.ws.connection_manager`, which serves the
public arena rooms an OBS browser source connects to without authenticating.
Gift IDs, sender handles and raw provider payloads go out on this channel and
must never reach a viewer's screen (section 18), so keeping them in different
objects means there is no room id that could accidentally carry one into the
other.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger("admin_ws")


class AdminChannel:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def broadcast(self, message: dict) -> None:
        if not self._clients:
            return
        payload = json.dumps(message, default=str)
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast_soon(self, message: dict) -> None:
        """Fire-and-forget, for callers that are not async.

        The monitor feed is diagnostics: it must never delay, or fail, the
        handling of a real gift.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._safe_broadcast(message))

    async def _safe_broadcast(self, message: dict) -> None:
        try:
            await self.broadcast(message)
        except Exception:
            logger.debug("admin broadcast failed", exc_info=True)


admin_channel = AdminChannel()
