"""Generating a character's animation frames with an image model.

The hard part of a sprite sheet is not drawing one good pose, it is drawing
several that match: same character, same framing, same size. Image models are
bad at repeating themselves from a text prompt alone, so everything here is
built from a single reference image -- either one the admin uploaded or one
generated from their description. Every other image, including the reaction
stills, is an *edit* of that reference: identity comes from the picture, and
the prompt only says what changed.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Callable

import httpx
from PIL import Image

from app.core.config import settings
from app.services import secret_store
from app.services.image_providers import ImageProvider, ImageProviderError, build, catalog
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


class SpriteStudioError(ImageProviderError):
    """Something the admin can act on -- shown as-is in the panel.

    Subclasses the provider error so a failure raised deep inside a provider
    reaches the panel with its own wording intact.
    """


# What the panel offers. The list comes from the provider classes themselves.
PROVIDER_CATALOG = catalog


async def resolve_provider() -> str:
    """Which service is drawing right now."""
    chosen = await secret_store.get(_PROVIDER_SETTING)
    return (chosen or settings.image_provider or "openai").lower()


async def set_provider(db, name: str) -> str:
    name = (name or "").lower()
    if name not in {entry["id"] for entry in catalog()}:
        raise SpriteStudioError(f"Provedor desconhecido: {name!r}.")
    await secret_store.set_value(db, _PROVIDER_SETTING, name)
    return name


_PROVIDER_SETTING = "image_provider"


def _env_key(provider: str) -> str:
    return {
        "openai": settings.image_api_key,
        "gemini": settings.gemini_api_key,
        "aisa": settings.aisa_api_key,
    }.get(provider, "")


async def resolve_key(provider: str | None = None) -> tuple[str | None, str | None]:
    """The key in use for a provider and where it came from.

    Each service has its own key, so switching provider does not mean pasting
    over the previous one. A key pasted in the panel wins over the server's
    environment, otherwise saving a new key would appear to do nothing.
    """
    provider = provider or await resolve_provider()
    saved = await secret_store.get(secret_store.image_key_name(provider))
    if saved:
        return saved, "panel"
    from_env = _env_key(provider)
    if from_env:
        return from_env, "env"
    return None, None


async def is_configured() -> bool:
    key, _ = await resolve_key()
    return bool(key)


_ENV_VAR = {
    "openai": "BATTLE_IMAGE_API_KEY",
    "gemini": "BATTLE_GEMINI_API_KEY",
    "aisa": "BATTLE_AISA_API_KEY",
}


async def _require_key(provider: str) -> str:
    key, _ = await resolve_key(provider)
    if not key:
        raise SpriteStudioError(
            f"Nenhuma chave configurada para {provider}. Cole a chave em "
            f"Admin -> Gerar sprites, ou defina {_ENV_VAR.get(provider, 'a variável')} "
            "no .env do servidor."
        )
    return key


def _as_png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _edit_instruction(instruction: str) -> str:
    """The whole trick: identity comes from the reference, not from the words."""
    return (
        "Keep the exact same character, art style, colors, size and framing "
        f"as the reference image. Change only this: {instruction}. {STYLE_RULES}"
    )


@dataclass
class StudioResult:
    """Everything one run produced: the looping sheet plus the reaction stills."""

    sheet: SheetLayout | None
    hit: bytes | None
    fire: bytes | None


async def generate_artwork(
    description: str,
    poses: list[str],
    base_image: bytes | None = None,
    want_hit: bool = False,
    want_fire: bool = False,
    columns: int = 0,
    size: str = DEFAULT_SIZE,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> StudioResult:
    """Produces a character's art in one run.

    The reference image is either uploaded by the admin (a caricature they
    already have) or generated from `description`. Everything else -- the other
    idle poses, the taking-a-hit still, the firing still -- is an edit of that
    one reference, because a model cannot redraw the same character twice from
    words but can modify one it is given.
    """
    poses = [p.strip() for p in poses if p.strip()]
    if base_image is None and not description.strip():
        raise SpriteStudioError("Descreva o personagem ou envie uma imagem base.")
    if not poses and not want_hit and not want_fire:
        raise SpriteStudioError("Escolha pelo menos uma pose ou uma imagem de ação.")

    frames: list[Image.Image] = []
    provider_name = await resolve_provider()
    key = await _require_key(provider_name)
    provider: ImageProvider = build(provider_name, key)
    if size == DEFAULT_SIZE:
        # Each service accepts a different frame size; honour an explicit
        # choice but fall back to whatever this one actually takes.
        size = provider.default_size

    # Each image is a separate call to the provider and takes its own handful
    # of seconds, so the caller is told where we are rather than being left to
    # guess whether a long wait is progress or a hang.
    total = (len(poses) if base_image is None else len(poses) + 1)
    total += (1 if want_hit else 0) + (1 if want_fire else 0)
    done = 0

    def step(label: str) -> None:
        nonlocal done
        done += 1
        if on_progress:
            on_progress(done, total, label)

    async with provider.open_client() as client:
        if base_image is not None:
            # The uploaded caricature is the character's neutral frame, and the
            # reference every other image is edited from.
            try:
                reference = Image.open(BytesIO(base_image)).convert("RGBA")
            except Exception as exc:  # noqa: BLE001 - anything unreadable is the same problem
                raise SpriteStudioError("Não consegui ler a imagem base enviada.") from exc
            frames.append(reference)
            pose_instructions = poses
            step("caricatura enviada")
        else:
            first = await provider.generate(
                client,
                f"{description.strip()}. {STYLE_RULES}. Pose: {poses[0]}",
                size,
            )
            frames.append(first)
            pose_instructions = poses[1:]
            logger.info("sprite studio: quadro 1 gerado do texto")
            step("quadro 1")

        reference_png = _as_png(frames[0])

        for index, pose in enumerate(pose_instructions, start=len(frames) + 1):
            frames.append(
                await provider.edit(
                    client, reference_png, _edit_instruction(f"the pose becomes {pose}"), size
                )
            )
            logger.info("sprite studio: quadro %d gerado", index)
            step(f"quadro {index}")

        hit = fire = None
        if want_hit:
            hit = _as_png(
                await provider.edit(
                    client,
                    reference_png,
                    _edit_instruction(
                        "the character is being hit and hurt right now: recoiling backwards, "
                        "face twisted in pain, eyes squeezed shut, arms thrown up defensively"
                    ),
                    size,
                )
            )
            logger.info("sprite studio: imagem de dano gerada")
            step("pose de dano")
        if want_fire:
            fire = _as_png(
                await provider.edit(
                    client,
                    reference_png,
                    _edit_instruction(
                        "the character is attacking right now: throwing a bomb with one arm "
                        "stretched out, leaning forward, determined shouting expression"
                    ),
                    size,
                )
            )
            logger.info("sprite studio: imagem de disparo gerada")
            step("pose de ataque")

    sheet = compose_sheet(frames, columns=columns) if frames else None
    return StudioResult(sheet=sheet, hit=hit, fire=fire)


async def verify_key(candidate: str | None = None, provider: str | None = None) -> str:
    """Checks a key against the service without generating anything.

    Listing models costs nothing, so the panel can confirm a key works before
    the admin spends credits finding out that it does not.
    """
    provider_name = provider or await resolve_provider()
    key = candidate or await _require_key(provider_name)
    built = build(provider_name, key)
    async with built.open_client() as client:
        return await built.verify(client)
