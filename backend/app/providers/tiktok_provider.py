import logging
import time

from app.providers.base import LiveEventProvider
from app.schemas.schemas import LiveEvent, LiveGift, LiveUser

logger = logging.getLogger("tiktok_provider")


class TikTokProvider(LiveEventProvider):
    """Phase 7 of the spec's MVP ordering: only wired up *after* the core
    flow works end-to-end via the simulator. Connects to a TikTok LIVE
    using the community `TikTokLive` client and translates its gift/join
    events into the same standard LiveEvent the rest of the pipeline
    already understands -- no game logic lives in this file.

    The `TikTokLive` package is an optional dependency (not in
    requirements.txt by default) since it requires network access to
    TikTok's live signaling servers, which isn't available in every
    deployment environment. Install it with `pip install TikTokLive` and
    call start(session_id, tiktok_username="...") to go live.
    """

    def __init__(self) -> None:
        super().__init__()
        self._clients: dict[str, object] = {}

    async def start(self, session_id: str, tiktok_username: str | None = None, **kwargs) -> None:
        if not tiktok_username:
            raise ValueError("tiktok_username is required to start TikTokProvider")

        try:
            from TikTokLive import TikTokLiveClient
            from TikTokLive.events import CommentEvent, ConnectEvent, GiftEvent
        except ImportError as exc:
            raise RuntimeError(
                "TikTokLive package not installed. Run `pip install TikTokLive` to enable "
                "the real TikTok LIVE provider."
            ) from exc

        client = TikTokLiveClient(unique_id=f"@{tiktok_username.lstrip('@')}")

        @client.on(ConnectEvent)
        async def _on_connect(_event):
            logger.info("connected to tiktok live @%s for session=%s", tiktok_username, session_id)

        @client.on(GiftEvent)
        async def _on_gift(event):
            live_event = LiveEvent(
                type="gift_received",
                user=LiveUser(
                    id=str(event.user.user_id),
                    username=event.user.unique_id,
                    nickname=event.user.nickname,
                    avatar=str(event.user.avatar_thumb.url_list[0]) if event.user.avatar_thumb else None,
                ),
                gift=LiveGift(
                    id=str(event.gift.id),
                    name=event.gift.name,
                    quantity=event.repeat_count or 1,
                ),
                timestamp=time.time(),
                raw={"combo": bool(event.gift.combo)},
            )
            await self.emit(session_id, live_event)

        @client.on(CommentEvent)
        async def _on_comment(event):
            # Tank war mode enlists viewers from chat keywords, so comments
            # are a first-class event, not just decoration.
            live_event = LiveEvent(
                type="comment",
                user=LiveUser(
                    id=str(event.user.user_id),
                    username=event.user.unique_id,
                    nickname=event.user.nickname,
                    avatar=str(event.user.avatar_thumb.url_list[0]) if event.user.avatar_thumb else None,
                ),
                comment=event.comment,
                timestamp=time.time(),
            )
            await self.emit(session_id, live_event)

        self._clients[session_id] = client
        await client.start()

    async def stop(self, session_id: str) -> None:
        client = self._clients.pop(session_id, None)
        if client is not None:
            await client.disconnect()

    def is_connected(self, session_id: str) -> bool:
        return session_id in self._clients


tiktok_provider = TikTokProvider()
