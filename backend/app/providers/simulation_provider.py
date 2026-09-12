import time

from app.providers.base import LiveEventProvider
from app.schemas.schemas import LiveEvent, LiveGift, LiveUser


class SimulationProvider(LiveEventProvider):
    """Feeds hand-crafted events into the exact same pipeline a real TikTok
    LIVE would use. This is what powers the admin Simulator (section 45)
    and the stress-test tool (section 46) -- there is no separate "fake"
    animation logic anywhere."""

    async def start(self, session_id: str, **kwargs) -> None:
        return None

    async def stop(self, session_id: str) -> None:
        return None

    async def simulate_gift(
        self,
        session_id: str,
        user_id: str,
        username: str,
        gift_key: str,
        quantity: int = 1,
        nickname: str | None = None,
        avatar_url: str | None = None,
    ) -> None:
        event = LiveEvent(
            type="gift_received",
            user=LiveUser(id=user_id, username=username, nickname=nickname, avatar=avatar_url),
            gift=LiveGift(id=gift_key, name=gift_key, quantity=quantity),
            timestamp=time.time(),
        )
        await self.emit(session_id, event)

    async def simulate_join(
        self,
        session_id: str,
        user_id: str,
        username: str,
        nickname: str | None = None,
        avatar_url: str | None = None,
    ) -> None:
        event = LiveEvent(
            type="viewer_join",
            user=LiveUser(id=user_id, username=username, nickname=nickname, avatar=avatar_url),
            timestamp=time.time(),
        )
        await self.emit(session_id, event)

    async def simulate_comment(
        self,
        session_id: str,
        user_id: str,
        username: str,
        text: str,
        nickname: str | None = None,
        avatar_url: str | None = None,
    ) -> None:
        event = LiveEvent(
            type="comment",
            user=LiveUser(id=user_id, username=username, nickname=nickname, avatar=avatar_url),
            comment=text,
            timestamp=time.time(),
        )
        await self.emit(session_id, event)


simulation_provider = SimulationProvider()
