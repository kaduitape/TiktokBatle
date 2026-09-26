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
            # A simulated participant -- the autopilot, the stress test, or the
            # admin's manual "send gift" button -- is rehearsal, not audience.
            # It still fires the configured rule (see GamePipeline._resolve_gift,
            # which reads gifts by key here and never touches the catalogue),
            # but it must not bump times_received or appear in the discovery
            # feed: those describe who is actually watching the LIVE.
            raw={"skip_catalog_capture": True},
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
        skip_catalog: bool = True,
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
                # Replaying an already-catalogued gift to test its rule is the
                # same rehearsal as simulate_gift above, so it is silent by
                # default too. /api/simulator/platform-gift is the one caller
                # that turns this off: its whole job is letting an admin watch
                # a brand-new gift ID go through capture before it happens on
                # a real LIVE.
                "skip_catalog_capture": skip_catalog,
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
        team: str | None = None,
    ) -> None:
        event = LiveEvent(
            type="viewer_join",
            user=LiveUser(id=user_id, username=username, nickname=nickname, avatar=avatar_url),
            timestamp=time.time(),
            # A real join has no team hint. The simulator needs one so an
            # explicit A/B quota can be honoured without creating a player on
            # one side and switching it a moment later with a second event.
            raw={"simulated": True, "simulated_team": team} if team in ("A", "B") else {},
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

    async def simulate_like(
        self,
        session_id: str,
        user_id: str,
        username: str,
        count: int = 1,
        nickname: str | None = None,
        avatar_url: str | None = None,
    ) -> None:
        event = LiveEvent(
            type="like",
            user=LiveUser(id=user_id, username=username, nickname=nickname, avatar=avatar_url),
            timestamp=time.time(),
            raw={"simulated": True, "like_count": max(1, count)},
        )
        await self.emit(session_id, event)

    async def simulate_follow(
        self,
        session_id: str,
        user_id: str,
        username: str,
        nickname: str | None = None,
        avatar_url: str | None = None,
    ) -> None:
        event = LiveEvent(
            type="follow",
            user=LiveUser(id=user_id, username=username, nickname=nickname, avatar=avatar_url),
            timestamp=time.time(),
            raw={"simulated": True},
        )
        await self.emit(session_id, event)


simulation_provider = SimulationProvider()
