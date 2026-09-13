"""Generating a character's animation frames with an image model.

The hard part of a sprite sheet is not drawing one good pose, it is drawing
several that match: same character, same framing, same size. Image models are
bad at repeating themselves from a text prompt alone, so this generates the
first pose and then asks the model to *edit that same image* for every pose
after it. The base image carries the identity; the prompt only says what moved.
"""
from __future__ import annotations

import base64
import logging
from io import BytesIO

import httpx
from PIL import Image

from app.core.config import settings
from app.services.sprite_sheet import SheetLayout, compose_sheet

logger = logging.getLogger("sprite_studio")

# Portrait frame: characters are drawn standing, and the arena is 9:16.
DEFAULT_SIZE = "1024x1536"

# Everything the art has to hold constant for the frames to line up. Written
# once here and appended to every prompt, so the admin only describes the
# character and the poses.
STYLE_RULES = (
    "full body, head to feet, facing the camera, "
    "centered in frame with the feet at the bottom edge, "
    "completely transparent background, no ground shadow, no scenery, "
    "flat even lighting, consistent cartoon caricature style, "
    "the character must fill the same amount of the frame in every image"
)


class SpriteStudioError(RuntimeError):
    """Something the admin can act on -- shown as-is in the panel."""


def is_configured() -> bool:
    return bool(settings.image_api_key)


def _require_key() -> str:
    if not settings.image_api_key:
        raise SpriteStudioError(
            "Nenhuma chave de imagem configurada. Defina BATTLE_IMAGE_API_KEY no .env "
            "e reinicie o backend."
        )
    return settings.image_api_key


def _decode(payload: dict) -> Image.Image:
    try:
        b64 = payload["data"][0]["b64_json"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SpriteStudioError(f"Resposta inesperada da API de imagem: {payload}") from exc
    return Image.open(BytesIO(base64.b64decode(b64))).convert("RGBA")


def _explain(response: httpx.Response) -> str:
    """Surfaces the provider's own message; a generic 'deu erro' would leave
    the admin guessing between a bad key, no credit, and a rejected prompt."""
    try:
        detail = response.json().get("error", {}).get("message")
    except Exception:  # noqa: BLE001 - a non-JSON error body is still useful
        detail = None
    detail = detail or response.text[:300]
    if response.status_code in (401, 403):
        return f"A chave de imagem foi recusada ({response.status_code}): {detail}"
    if response.status_code == 429:
        return f"Limite da API de imagem atingido: {detail}"
    return f"A API de imagem respondeu {response.status_code}: {detail}"


async def _post(client: httpx.AsyncClient, path: str, **kwargs) -> Image.Image:
    try:
        response = await client.post(path, **kwargs)
    except httpx.HTTPError as exc:
        raise SpriteStudioError(f"Não foi possível falar com a API de imagem: {exc}") from exc
    if response.status_code >= 400:
        raise SpriteStudioError(_explain(response))
    return _decode(response.json())


async def generate_frames(
    description: str,
    poses: list[str],
    size: str = DEFAULT_SIZE,
) -> list[Image.Image]:
    """First pose from text, every other pose as an edit of that first image."""
    key = _require_key()
    if not description.strip():
        raise SpriteStudioError("Descreva o personagem antes de gerar.")
    poses = [p.strip() for p in poses if p.strip()]
    if not poses:
        raise SpriteStudioError("Informe pelo menos uma pose.")

    headers = {"Authorization": f"Bearer {key}"}
    frames: list[Image.Image] = []

    try:
        client = httpx.AsyncClient(
            base_url=settings.image_api_base.rstrip("/"),
            headers=headers,
            timeout=settings.image_timeout_seconds,
        )
    except httpx.InvalidURL as exc:
        # A typo in BATTLE_IMAGE_API_BASE would otherwise blow up as an opaque
        # 500 with no hint about which setting is wrong.
        raise SpriteStudioError(
            f"BATTLE_IMAGE_API_BASE inválido ({settings.image_api_base!r}): {exc}"
        ) from exc

    async with client:
        first = await _post(
            client,
            "/images/generations",
            json={
                "model": settings.image_model,
                "prompt": f"{description.strip()}. {STYLE_RULES}. Pose: {poses[0]}",
                "size": size,
                "background": "transparent",
                "output_format": "png",
                "n": 1,
            },
        )
        frames.append(first)
        logger.info("sprite studio: pose 1/%d gerada", len(poses))

        for index, pose in enumerate(poses[1:], start=2):
            buffer = BytesIO()
            first.save(buffer, format="PNG")
            buffer.seek(0)
            edited = await _post(
                client,
                "/images/edits",
                data={
                    "model": settings.image_model,
                    "prompt": (
                        "Keep the exact same character, art style, colors, size and framing "
                        f"as the reference image. Change only the pose to: {pose}. {STYLE_RULES}"
                    ),
                    "size": size,
                    "background": "transparent",
                    "n": "1",
                },
                files={"image": ("base.png", buffer.getvalue(), "image/png")},
            )
            frames.append(edited)
            logger.info("sprite studio: pose %d/%d gerada", index, len(poses))

    return frames


async def generate_sheet(
    description: str,
    poses: list[str],
    columns: int = 0,
    size: str = DEFAULT_SIZE,
) -> SheetLayout:
    frames = await generate_frames(description, poses, size=size)
    return compose_sheet(frames, columns=columns)
