"""Optional bulk import of the room's gift list.

Some provider versions expose the gifts a room offers, which lets the whole
catalogue be filled before anybody sends anything. It is strictly an
accelerator: capture by event is the mechanism that must always work, and
this one degrades to "not available" rather than to an error when the
provider has no such call.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.tiktok_provider import tiktok_provider
from app.services.gift_catalog_service import gift_catalog_service
from app.services.gift_normalizer import CapturedGift

logger = logging.getLogger("gift_catalog_sync")


class GiftCatalogSync:
    async def sync(self, db: AsyncSession, session_id: str | None) -> dict[str, Any]:
        raw_gifts = await self._fetch(session_id)
        if raw_gifts is None:
            return {
                "available": False,
                "reason": (
                    "Esta versão do provider não expõe o catálogo da sala. "
                    "A captura por evento continua funcionando normalmente."
                ),
                "added": 0,
                "updated": 0,
                "unchanged": 0,
            }

        added = updated = unchanged = 0
        for raw in raw_gifts:
            captured = self._to_captured(raw)
            if captured is None:
                continue
            # count_receipt=False: listing a gift is not the same as somebody
            # sending one, and inflating times_received would make the
            # "recebidos" column meaningless.
            result = await gift_catalog_service.register_or_update(
                db, captured, count_receipt=False
            )
            if result.is_new:
                added += 1
                await gift_catalog_service.cache_artwork(db, result.entry)
            elif result.was_enriched:
                updated += 1
            else:
                unchanged += 1

        await db.commit()
        logger.info("catálogo sincronizado: +%s novos, %s atualizados", added, updated)
        return {
            "available": True,
            "added": added,
            "updated": updated,
            "unchanged": unchanged,
        }

    async def _fetch(self, session_id: str | None) -> list[Any] | None:
        """Ask the provider for the room's gift list, if it can answer."""
        if session_id is None:
            return None
        client = tiktok_provider.client_for(session_id)
        if client is None:
            return None

        for attribute in ("available_gifts", "gifts"):
            gifts = getattr(client, attribute, None)
            if gifts:
                return list(gifts)

        fetch = getattr(client, "fetch_available_gifts", None)
        if callable(fetch):
            try:
                result = await fetch()
                return list(result) if result else []
            except Exception as exc:
                logger.info("provider não conseguiu listar o catálogo: %s", exc)
                return None
        return None

    @staticmethod
    def _to_captured(raw: Any) -> CapturedGift | None:
        gift_id = getattr(raw, "id", None) or (raw.get("id") if isinstance(raw, dict) else None)
        if gift_id in (None, ""):
            return None

        def field(*names):
            for name in names:
                value = (
                    raw.get(name) if isinstance(raw, dict) else getattr(raw, name, None)
                )
                if value not in (None, ""):
                    return value
            return None

        diamonds = field("diamond_count", "diamond", "coins")
        try:
            diamonds = int(diamonds) if diamonds is not None else None
        except (TypeError, ValueError):
            diamonds = None

        image = field("image", "icon")
        image_url = None
        if image is not None:
            urls = getattr(image, "url_list", None) or (
                image.get("url_list") if isinstance(image, dict) else None
            )
            image_url = str(urls[0]) if urls else (str(image) if isinstance(image, str) else None)

        return CapturedGift(
            platform="tiktok",
            platform_gift_id=str(gift_id),
            name=str(field("name") or "") or None,
            image_url=image_url,
            diamond_value=diamonds,
            coin_value=diamonds,
            quantity=0,
            metadata={"source": "catalog_sync"},
        )


gift_catalog_sync = GiftCatalogSync()
