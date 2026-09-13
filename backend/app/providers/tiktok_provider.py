"""TikTok LIVE ingress with lifecycle tracking and safe event normalisation."""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.providers.base import LiveEventProvider
from app.schemas.schemas import LiveEvent, LiveGift, LiveUser

logger = logging.getLogger("tiktok_provider")


@dataclass
class LiveConnection:
    username: str
    state: str = "connecting"  # connecting|connected|reconnecting|error|disconnected
    client: Any | None = None
    task: asyncio.Task | None = None
    reconnect_task: asyncio.Task | None = None
    stop_requested: bool = False
    last_error: str | None = None
    reconnect_attempt: int = 0
    connected_at: float | None = None
    last_event_at: float | None = None
    events_received: int = 0


class TikTokProvider(LiveEventProvider):
    """Receive a real TikTok LIVE and feed its events into the game queue.

    TikTokLive is deliberately isolated here. The rest of the application only
    sees the project's normalized ``LiveEvent`` and therefore remains testable
    through the simulator. Each session owns one client and reconnects after a
    dropped websocket until an operator explicitly disconnects it.
    """

    def __init__(self) -> None:
        super().__init__()
        self._connections: dict[str, LiveConnection] = {}

    async def start(self, session_id: str, tiktok_username: str | None = None, **kwargs) -> None:
        if not tiktok_username:
            raise ValueError("tiktok_username is required to start TikTokProvider")

        existing = self._connections.get(session_id)
        if existing and existing.state in {"connecting", "connected", "reconnecting"}:
            raise ValueError("TikTok LIVE is already active for this session")

        connection = LiveConnection(username=tiktok_username.lstrip("@"))
        self._connections[session_id] = connection
        try:
            await self._open_client(session_id, connection)
        except Exception as exc:
            connection.state = "error"
            connection.last_error = self._error_message(exc)
            logger.exception("unable to connect to TikTok LIVE @%s", connection.username)
            raise

    async def _open_client(self, session_id: str, connection: LiveConnection) -> None:
        """Open a fresh TikTokLive client and attach all event handlers."""
        try:
            from TikTokLive import TikTokLiveClient
            from TikTokLive.events import (
                CommentEvent,
                ConnectEvent,
                DisconnectEvent,
                GiftEvent,
                JoinEvent,
            )
        except ImportError as exc:
            raise RuntimeError(
                "TikTokLive is not installed in the backend image. Rebuild the deployment "
                "after updating backend/requirements.txt."
            ) from exc

        client = TikTokLiveClient(unique_id=f"@{connection.username}")
        connection.client = client
        connection.state = "connecting"
        connection.last_error = None

        @client.on(ConnectEvent)
        async def _on_connect(event: Any) -> None:
            current = self._connections.get(session_id)
            if current is not connection or current.stop_requested:
                return
            current.state = "connected"
            current.reconnect_attempt = 0
            current.connected_at = time.time()
            logger.info(
                "connected to TikTok LIVE @%s room=%s session=%s",
                connection.username,
                getattr(event, "room_id", None),
                session_id,
            )

        @client.on(DisconnectEvent)
        async def _on_disconnect(_event: Any) -> None:
            current = self._connections.get(session_id)
            if current is connection and not current.stop_requested:
                current.state = "reconnecting"
                current.last_error = "TikTok LIVE disconnected; reconnecting automatically"

        @client.on(GiftEvent)
        async def _on_gift(event: Any) -> None:
            # A streak emits intermediate events with a cumulative
            # repeat_count. The final non-streaking event contains the whole
            # quantity; processing intermediates would multiply damage.
            if bool(getattr(event, "streaking", False)):
                return

            user = self._live_user(event)
            gift = getattr(event, "gift", None)
            gift_id = getattr(event, "gift_id", None) or getattr(gift, "id", None)
            if user is None or gift is None or gift_id is None:
                logger.warning("ignored malformed TikTok gift event for session=%s", session_id)
                return

            quantity = max(1, self._as_int(getattr(event, "repeat_count", 1), default=1))
            coins = getattr(gift, "diamond_count", None)
            live_event = LiveEvent(
                type="gift_received",
                user=user,
                gift=LiveGift(
                    id=str(gift_id),
                    name=str(getattr(gift, "name", None) or gift_id),
                    quantity=quantity,
                ),
                timestamp=time.time(),
                raw={
                    "provider": "tiktok",
                    "tiktok_gift_id": str(gift_id),
                    "coins": self._as_int(coins, default=0) if coins is not None else None,
                    "streak": bool(getattr(event, "streaking", False)),
                },
            )
            await self._emit_live_event(session_id, connection, live_event)

        @client.on(CommentEvent)
        async def _on_comment(event: Any) -> None:
            user = self._live_user(event)
            if user is None:
                return
            live_event = LiveEvent(
                type="comment",
                user=user,
                comment=str(getattr(event, "comment", "") or ""),
                timestamp=time.time(),
                raw={"provider": "tiktok"},
            )
            await self._emit_live_event(session_id, connection, live_event)

        @client.on(JoinEvent)
        async def _on_join(event: Any) -> None:
            user = self._live_user(event)
            if user is None:
                return
            live_event = LiveEvent(
                type="viewer_join",
                user=user,
                timestamp=time.time(),
                raw={"provider": "tiktok"},
            )
            await self._emit_live_event(session_id, connection, live_event)

        # TikTokLive.start performs the initial room/live check and then
        # returns the websocket task; it does not block FastAPI's event loop.
        task = await client.start()
        connection.task = task
        task.add_done_callback(
            lambda finished: asyncio.create_task(
                self._handle_client_finished(session_id, connection, finished)
            )
        )

    async def _emit_live_event(
        self, session_id: str, connection: LiveConnection, event: LiveEvent
    ) -> None:
        current = self._connections.get(session_id)
        if current is not connection or current.stop_requested:
            return
        current.events_received += 1
        current.last_event_at = time.time()
        await self.emit(session_id, event)

    async def _handle_client_finished(
        self, session_id: str, connection: LiveConnection, task: asyncio.Task
    ) -> None:
        """Update status and schedule recovery only for the current client."""
        current = self._connections.get(session_id)
        if current is not connection or current.task is not task:
            return

        error: Exception | None = None
        if not task.cancelled():
            try:
                task.result()
            except Exception as exc:  # the task owns websocket/library failures
                error = exc

        current.task = None
        current.client = None
        if current.stop_requested:
            current.state = "disconnected"
            return

        current.state = "reconnecting"
        current.last_error = self._error_message(error) if error else "TikTok LIVE ended or disconnected"
        logger.warning(
            "TikTok LIVE @%s ended for session=%s: %s",
            current.username,
            session_id,
            current.last_error,
        )
        self._schedule_reconnect(session_id, current)

    def _schedule_reconnect(self, session_id: str, connection: LiveConnection) -> None:
        if connection.stop_requested:
            return
        if connection.reconnect_task and not connection.reconnect_task.done():
            return
        connection.reconnect_task = asyncio.create_task(self._reconnect_loop(session_id, connection))

    async def _reconnect_loop(self, session_id: str, connection: LiveConnection) -> None:
        while self._connections.get(session_id) is connection and not connection.stop_requested:
            connection.reconnect_attempt += 1
            delay = min(
                settings.tiktok_reconnect_seconds * (2 ** (connection.reconnect_attempt - 1)),
                settings.tiktok_reconnect_max_seconds,
            )
            connection.state = "reconnecting"
            logger.info(
                "reconnecting TikTok LIVE @%s in %ss (attempt %s)",
                connection.username,
                delay,
                connection.reconnect_attempt,
            )
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return

            if connection.stop_requested or self._connections.get(session_id) is not connection:
                return

            try:
                await self._open_client(session_id, connection)
                return
            except Exception as exc:
                connection.last_error = self._error_message(exc)
                logger.warning(
                    "TikTok LIVE reconnect failed for session=%s: %s",
                    session_id,
                    connection.last_error,
                )

    async def stop(self, session_id: str) -> None:
        connection = self._connections.get(session_id)
        if connection is None:
            return

        connection.stop_requested = True
        if connection.reconnect_task and not connection.reconnect_task.done():
            connection.reconnect_task.cancel()

        client = connection.client
        connection.client = None
        if client is not None:
            try:
                await client.disconnect(close_client=True)
            except TypeError:
                # Older TikTokLive releases do not expose close_client.
                await client.disconnect()
            except Exception:
                logger.debug("error while disconnecting TikTok LIVE", exc_info=True)

        connection.task = None
        connection.state = "disconnected"
        connection.last_error = None

    def is_connected(self, session_id: str) -> bool:
        connection = self._connections.get(session_id)
        return bool(connection and connection.state in {"connecting", "connected", "reconnecting"})

    def status(self, session_id: str) -> dict[str, Any]:
        connection = self._connections.get(session_id)
        if connection is None:
            return {
                "connected": False,
                "state": "disconnected",
                "username": None,
                "last_error": None,
                "reconnect_attempt": 0,
                "events_received": 0,
                "connected_at": None,
                "last_event_at": None,
            }
        return {
            "connected": connection.state == "connected",
            "state": connection.state,
            "username": connection.username,
            "last_error": connection.last_error,
            "reconnect_attempt": connection.reconnect_attempt,
            "events_received": connection.events_received,
            "connected_at": connection.connected_at,
            "last_event_at": connection.last_event_at,
        }

    @staticmethod
    def _live_user(event: Any) -> LiveUser | None:
        user = getattr(event, "user", None)
        if user is None:
            return None
        user_id = getattr(user, "id", None) or getattr(user, "user_id", None) or getattr(event, "user_id", None)
        username = getattr(user, "unique_id", None) or getattr(user, "display_id", None) or str(user_id or "")
        if user_id is None or not username:
            return None
        return LiveUser(
            id=str(user_id),
            username=str(username),
            nickname=getattr(user, "nickname", None),
            avatar=TikTokProvider._avatar_url(user),
        )

    @staticmethod
    def _avatar_url(user: Any) -> str | None:
        for attr in ("avatar_thumb", "avatar_medium", "avatar_large"):
            image = getattr(user, attr, None)
            urls = getattr(image, "url_list", None) if image else None
            if urls:
                return str(urls[0])
        return None

    @staticmethod
    def _as_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _error_message(error: Exception | None) -> str:
        if error is None:
            return "connection closed"
        return str(error).strip() or error.__class__.__name__


tiktok_provider = TikTokProvider()
