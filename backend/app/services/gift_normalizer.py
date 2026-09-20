"""Turn whatever a provider sends about a gift into one predictable shape.

TikTok's payload is not a contract. Field names move between library versions,
some rooms send a diamond count and others do not, and a streak arrives either
as one final event or as a running series of updates. Every one of those
differences is absorbed here so that nothing downstream -- the catalogue, the
rule engine, the game -- ever reads a provider-specific attribute.

The rule the whole module follows: record what the provider actually said.
A field the provider omitted stays ``None``; it is never defaulted into a
number that would later look like a measurement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.schemas.schemas import LiveEvent

logger = logging.getLogger("gift_normalizer")

# Keys we lift into columns of their own; everything else lands in metadata.
_PROMOTED_KEYS = {
    "provider",
    "tiktok_gift_id",
    "platform_gift_id",
    "coins",
    "diamond_count",
    "gift_image_url",
    "image_url",
    "repeat_count",
    "repeat_end",
    "combo_id",
    "streak",
}


@dataclass
class CapturedSender:
    """Who sent it. Only ``user_id`` and ``username`` are ever guaranteed."""

    user_id: str
    username: str
    nickname: str | None = None
    avatar_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "nickname": self.nickname,
            "avatar_url": self.avatar_url,
        }


@dataclass
class CapturedGift:
    """One gift event, normalised.

    ``quantity`` is what the game should act on *now*. For a provider that
    reports a running streak total, that is the newly added amount rather than
    the cumulative count -- see :class:`GiftStreakGuard`.
    """

    platform: str
    platform_gift_id: str
    name: str | None = None
    image_url: str | None = None
    diamond_value: int | None = None
    coin_value: int | None = None
    quantity: int = 1
    repeat_count: int | None = None
    repeat_end: bool | None = None
    combo_id: str | None = None
    timestamp: float = 0.0
    sender: CapturedSender | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def catalog_key(self) -> tuple[str, str]:
        return (self.platform, self.platform_gift_id)


class GiftNormalizer:
    """Reads a :class:`LiveEvent` and produces a :class:`CapturedGift`."""

    @staticmethod
    def normalize(event: LiveEvent) -> CapturedGift | None:
        if event.type != "gift_received" or event.gift is None:
            return None

        raw = event.raw or {}
        platform = str(raw.get("provider") or "simulator")

        # The ID is the only field the catalogue cannot do without. Providers
        # disagree on where they put it, so try the explicit ones before
        # falling back to the event's own gift id.
        platform_gift_id = (
            raw.get("platform_gift_id")
            or raw.get("tiktok_gift_id")
            or event.gift.id
        )
        if platform_gift_id in (None, ""):
            logger.warning("gift event without any usable id, ignored: %s", raw)
            return None

        repeat_count = _as_int(raw.get("repeat_count"))
        quantity = event.gift.quantity if event.gift.quantity and event.gift.quantity > 0 else 1

        diamonds = _as_int(raw.get("diamond_count"))
        coins = _as_int(raw.get("coins"))
        # TikTok's "coins" and "diamonds" are the same price under two names;
        # whichever one arrived stands in for the other.
        if diamonds is None and coins is not None:
            diamonds = coins
        if coins is None and diamonds is not None:
            coins = diamonds

        return CapturedGift(
            platform=platform,
            platform_gift_id=str(platform_gift_id),
            name=(event.gift.name or None),
            image_url=_first_str(raw.get("gift_image_url"), raw.get("image_url")),
            diamond_value=diamonds,
            coin_value=coins,
            quantity=quantity,
            repeat_count=repeat_count,
            repeat_end=_as_bool(raw.get("repeat_end")),
            combo_id=_first_str(raw.get("combo_id")),
            timestamp=event.timestamp or 0.0,
            sender=CapturedSender(
                user_id=event.user.id,
                username=event.user.username,
                nickname=event.user.nickname,
                avatar_url=event.user.avatar,
            ),
            # Anything the provider sent that has no column. This is what makes
            # a changed TikTok payload diagnosable instead of invisible.
            metadata={k: v for k, v in raw.items() if k not in _PROMOTED_KEYS},
        )


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _first_str(*values: Any) -> str | None:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return None


gift_normalizer = GiftNormalizer()
