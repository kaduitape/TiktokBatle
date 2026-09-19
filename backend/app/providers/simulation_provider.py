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

    async def simulate_catalog_gift(
        self,
        session_id: str,
        user_id: str,
        username: str,
        platform: str,
        platform_gift_id: str,
        gift_name: str,
        quantity: int = 1,
        diamond_value: int | None = None,
        image_url: str | None = None,
        nickname: str | None = None,
        avatar_url: str | None = None,
        repeat_end: bool = True,
    ) -> None:
        """Replay a catalogued gift exactly as its platform would send it.

        Section 15: the simulator must not have a path of its own. This builds
        the same LiveEvent shape the real provider produces -- same platform,
        same ID, same streak fields -- so it goes through the normalizer, the
        catalogue, the streak guard and the rule engine like any other gift.
        A "Rose x50" simulated here is indistinguishable downstream from a
        Rose x50 sent by a real viewer.
        """
        event = LiveEvent(
            type="gift_received",
            user=LiveUser(id=user_id, username=username, nickname=nickname, avatar=avatar_url),
            gift=LiveGift(id=str(platform_gift_id), name=gift_name, quantity=quantity),
            timestamp=time.time(),
            raw={
                "provider": platform,
                "platform_gift_id": str(platform_gift_id),
                "tiktok_gift_id": str(platform_gift_id),
                "diamond_count": diamond_value,
                "coins": diamond_value,
                "gift_image_url": image_url,
                "repeat_count": quantity,
                # By default one self-contained event, like the closing event
                # of a real streak, so the guard applies the whole quantity
                # once. Pass repeat_end=False to replay an intermediate update.
                "repeat_end": repeat_end,
                "simulated": True,
            },
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
