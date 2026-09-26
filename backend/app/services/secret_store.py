"""Private settings saved by the sprite panel.

The application database and uploads are intentionally committed to Git so a
deployment receives the registered characters and configuration. Credentials
must never join that history, so provider keys and the selected provider live
in a small ignored JSON file mounted at ``/app/private`` instead.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

IMAGE_API_KEY = "image_api_key"
_LOCK = asyncio.Lock()


def image_key_name(provider: str) -> str:
    provider = (provider or "openai").lower()
    return IMAGE_API_KEY if provider == "openai" else f"{IMAGE_API_KEY}:{provider}"


def _path() -> Path:
    return Path(settings.private_settings_file)


def _read() -> dict[str, str]:
    path = _path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): str(value) for key, value in raw.items() if value}


def _write(values: dict[str, str]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(values, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


async def get(name: str) -> str | None:
    async with _LOCK:
        return _read().get(name)


async def set_value(_db: AsyncSession, name: str, value: str) -> None:
    async with _LOCK:
        values = _read()
        values[name] = value
        _write(values)


async def clear(_db: AsyncSession, name: str) -> None:
    async with _LOCK:
        values = _read()
        if name in values:
            values.pop(name)
            _write(values)


def mask(value: str | None) -> str | None:
    """A preview that identifies which key is saved without revealing it."""
    if not value:
        return None
    tail = value[-4:] if len(value) > 4 else ""
    return f"{'•' * 6}{tail}"
