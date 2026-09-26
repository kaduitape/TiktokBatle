"""Orchestrates capture: normalise, record, announce.

This is the piece the pipeline calls. It owns three things the catalogue
itself has no opinion about:

* **Learning mode** -- a switch that lets an operator run a private LIVE and
  send gifts purely to discover their IDs. Everything is captured and shown,
  nothing damages, heals or changes XP.
* **The discovery list** -- which gifts turned up since capture was started,
  so the panel can say "8 presentes descobertos nesta sessão".
* **The event monitor** -- a short in-memory tail of raw events, which is the
  only practical way to see what a changed TikTok payload actually looks like.

None of this ever reaches the arena. It is broadcast on the admin channel,
which is authenticated and separate from the public game rooms.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.schemas import LiveEvent
from app.services.gift_catalog_service import CatalogResult, gift_catalog_service
from app.services.gift_normalizer import CapturedGift, gift_normalizer
from app.services.gift_repository import gift_repository
from app.services.gift_streak_guard import gift_streak_guard
from app.services.settings_service import settings_service
from app.ws.admin_channel import admin_channel

logger = logging.getLogger("gift_capture")

MONITOR_SIZE = 200


@dataclass
class CaptureOutcome:
    """What the pipeline needs to know after a gift has been captured."""

    captured: CapturedGift
    entry_id: str
    is_new: bool
    #: Quantity the game should act on, after streak deduplication.
    quantity: int
    #: True while learning mode is on -- capture only, no effect on the game.
    learning: bool


class GiftCaptureService:
    def __init__(self) -> None:
        self._discovered: dict[str, dict[str, Any]] = {}
        self._monitor: deque[dict[str, Any]] = deque(maxlen=MONITOR_SIZE)
        self._capturing = True

    # ------------------------------------------------------------------
    # Switches
    # ------------------------------------------------------------------

    async def learning_mode(self, db: AsyncSession) -> bool:
        config = await settings_service.get(db, "live_capture")
        return bool(config.get("learning_mode"))

    async def set_learning_mode(self, db: AsyncSession, enabled: bool) -> dict:
        config = await settings_service.get(db, "live_capture")
        config = {**config, "learning_mode": bool(enabled)}
        await settings_service.set(db, "live_capture", config)
        if enabled:
            self._discovered.clear()
        await admin_channel.broadcast(
            {"type": "gift_catalog:learning_mode", "enabled": bool(enabled)}
        )
        return config

    @property
    def capturing(self) -> bool:
        return self._capturing

    def set_capturing(self, enabled: bool) -> None:
        """Capture is on by default; this exists so an operator can silence the
        panel's live feed without disconnecting the LIVE."""
        self._capturing = bool(enabled)

    # ------------------------------------------------------------------
    # The capture itself
    # ------------------------------------------------------------------

    async def capture(
        self, db: AsyncSession, session_id: str, event: LiveEvent
    ) -> CaptureOutcome | None:
        captured = gift_normalizer.normalize(event)
        if captured is None:
            return None

        quantity = gift_streak_guard.applicable_quantity(session_id, captured)
        learning = await self.learning_mode(db)

        if event.raw and event.raw.get("skip_catalog_capture"):
            # A simulated participant -- the autopilot, the stress test, the
            # admin's manual "send gift" or "test from catalogue" buttons --
            # is rehearsal, not audience. Its gift still resolves and fires
            # through GamePipeline._resolve_gift exactly as a real one would
            # (that lookup never touches the catalogue), but nothing here
            # should bump times_received, appear in the discovery feed or the
            # live event monitor: those exist to describe who is actually
            # watching the LIVE, and a stress test of 200 fake viewers would
            # otherwise drown that out in seconds.
            return CaptureOutcome(
                captured=captured,
                entry_id="",
                is_new=False,
                quantity=quantity,
                learning=learning,
            )

        # The catalogue counts what the viewer actually sent, so a streak
        # already accounted for does not inflate times_received either.
        counting = CapturedGift(**{**captured.__dict__, "quantity": max(quantity, 0)})
        result = await gift_catalog_service.register_or_update(
            db, counting, count_receipt=quantity > 0
        )

        # Artwork is fetched once, on discovery, and never blocks the gift.
        if result.is_new or not result.entry.cached_image_url:
            await gift_catalog_service.cache_artwork(db, result.entry)

        await self._announce(db, session_id, captured, result, quantity, learning)

        return CaptureOutcome(
            captured=captured,
            entry_id=result.entry.id,
            is_new=result.is_new,
            quantity=quantity,
            learning=learning,
        )

    async def _announce(
        self,
        db: AsyncSession,
        session_id: str,
        captured: CapturedGift,
        result: CatalogResult,
        quantity: int,
        learning: bool,
    ) -> None:
        entry = result.entry
        sender = captured.sender.as_dict() if captured.sender else None
        rules = await gift_repository.rules_by_platform_id(db)
        rule = rules.get((entry.platform, entry.platform_gift_id))

        payload = {
            "platform": entry.platform,
            "gift_id": entry.platform_gift_id,
            "catalog_id": entry.id,
            "name": entry.name,
            "image_url": gift_catalog_service.display_image(entry),
            "value": entry.diamond_value,
            "times_received": entry.times_received,
            "configured": rule is not None,
            "sender": sender,
        }

        if result.is_new:
            self._discovered[entry.id] = {
                "catalog_id": entry.id,
                "gift_id": entry.platform_gift_id,
                "name": entry.name,
                "image_url": payload["image_url"],
                "value": entry.diamond_value,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            # Section 8: the panel shows a brand-new gift the moment it lands,
            # with no page refresh.
            await admin_channel.broadcast({"type": "gift_catalog:new", **payload})
        elif result.was_enriched:
            await admin_channel.broadcast({"type": "gift_catalog:updated", **payload})
        else:
            await admin_channel.broadcast({"type": "gift_catalog:seen", **payload})

        self._record_monitor(session_id, captured, entry, quantity, rule is not None, learning)

    def _record_monitor(
        self,
        session_id: str,
        captured: CapturedGift,
        entry,
        quantity: int,
        configured: bool,
        learning: bool,
    ) -> None:
        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "kind": "GIFT RECEIVED",
            "platform": captured.platform,
            "gift_id": captured.platform_gift_id,
            "gift_name": entry.name,
            "username": captured.sender.username if captured.sender else None,
            "quantity": captured.quantity,
            "applied_quantity": quantity,
            "repeat_count": captured.repeat_count,
            "repeat_end": captured.repeat_end,
            "combo_id": captured.combo_id,
            "configured": configured,
            "learning": learning,
            # The raw view exists to diagnose a provider whose payload changed.
            "raw": {
                "platform": captured.platform,
                "platform_gift_id": captured.platform_gift_id,
                "name": captured.name,
                "image_url": captured.image_url,
                "diamond_value": captured.diamond_value,
                "coin_value": captured.coin_value,
                "quantity": captured.quantity,
                "repeat_count": captured.repeat_count,
                "repeat_end": captured.repeat_end,
                "combo_id": captured.combo_id,
                "sender": captured.sender.as_dict() if captured.sender else None,
                "metadata": captured.metadata,
            },
        }
        self._monitor.append(record)
        if self._capturing:
            admin_channel.broadcast_soon({"type": "live_monitor:event", "event": record})

    # ------------------------------------------------------------------
    # Readers for the admin panel
    # ------------------------------------------------------------------

    def discovered(self) -> list[dict[str, Any]]:
        return sorted(self._discovered.values(), key=lambda item: item["at"])

    def clear_discovered(self) -> None:
        self._discovered.clear()

    def monitor(self, limit: int = 50) -> list[dict[str, Any]]:
        events = list(self._monitor)[-limit:]
        events.reverse()
        return events


gift_capture_service = GiftCaptureService()
