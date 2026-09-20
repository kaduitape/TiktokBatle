"""Keeps a local copy of each gift's artwork.

The platform serves gift icons from its own CDN with URLs that expire. A game
that fetches them live shows broken images halfway through a stream, so the
first time a gift is seen its icon is copied into the uploads directory and
everything afterwards points at that copy.

Downloading never blocks a gift from working: a failure here leaves
``cached_image_url`` empty and the panel falls back to the remote URL, then to
a placeholder. Artwork is decoration; the ID is the part the game needs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from io import BytesIO

import httpx

from app.core.config import settings

logger = logging.getLogger("gift_image_cache")

RELATIVE_DIR = "gifts"
PLACEHOLDER = "🎁"
_DOWNLOAD_TIMEOUT = 15.0
_MAX_BYTES = 2 * 1024 * 1024
_SAFE_ID = re.compile(r"[^a-zA-Z0-9_-]")


class GiftImageCache:
    def __init__(self) -> None:
        # One download per gift even when a hundred of them arrive at once.
        self._in_flight: set[tuple[str, str]] = set()

    def local_path(self, platform: str, gift_id: str) -> str:
        safe_platform = _SAFE_ID.sub("_", platform) or "unknown"
        safe_id = _SAFE_ID.sub("_", str(gift_id)) or "unknown"
        return os.path.join(settings.upload_dir, RELATIVE_DIR, safe_platform, f"{safe_id}.webp")

    def public_url(self, platform: str, gift_id: str) -> str:
        safe_platform = _SAFE_ID.sub("_", platform) or "unknown"
        safe_id = _SAFE_ID.sub("_", str(gift_id)) or "unknown"
        return f"/uploads/{RELATIVE_DIR}/{safe_platform}/{safe_id}.webp"

    def cached_url_if_present(self, platform: str, gift_id: str) -> str | None:
        return (
            self.public_url(platform, gift_id)
            if os.path.exists(self.local_path(platform, gift_id))
            else None
        )

    async def ensure(self, platform: str, gift_id: str, image_url: str | None) -> str | None:
        """Return the local URL, downloading the image first if needed."""
        if not image_url:
            return self.cached_url_if_present(platform, gift_id)

        existing = self.cached_url_if_present(platform, gift_id)
        if existing:
            return existing

        key = (platform, str(gift_id))
        if key in self._in_flight:
            return None
        self._in_flight.add(key)
        try:
            return await self._download(platform, gift_id, image_url)
        except Exception as exc:
            # A missing icon must never stop a gift from being captured.
            logger.info("could not cache artwork for %s/%s: %s", platform, gift_id, exc)
            return None
        finally:
            self._in_flight.discard(key)

    async def _download(self, platform: str, gift_id: str, image_url: str) -> str | None:
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(image_url)
            response.raise_for_status()
            payload = response.content

        if not payload or len(payload) > _MAX_BYTES:
            logger.info("artwork for %s/%s skipped: %s bytes", platform, gift_id, len(payload))
            return None

        path = self.local_path(platform, gift_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Pillow runs in a thread: it is CPU-bound and would otherwise stall
        # the event loop while a live stream is feeding events in.
        await asyncio.to_thread(_write_webp, payload, path)
        return self.public_url(platform, gift_id)


def _write_webp(payload: bytes, path: str) -> None:
    from PIL import Image

    with Image.open(BytesIO(payload)) as image:
        # Gift icons are usually transparent PNGs or animated WebPs; RGBA keeps
        # the transparency that makes them sit properly over the arena.
        image.load()
        converted = image.convert("RGBA")
        converted.save(path, format="WEBP", quality=88, method=4)


gift_image_cache = GiftImageCache()
