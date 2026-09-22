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


async def resolve_key() -> tuple[str | None, str | None]:
    """The key in use and where it came from.

    A key pasted in the panel wins over BATTLE_IMAGE_API_KEY, so the panel is
    always the last word on a server where both were set -- otherwise saving a
    new key would appear to do nothing.
    """
    saved = await secret_store.get(secret_store.IMAGE_API_KEY)
    if saved:
        return saved, "panel"
    if settings.image_api_key:
        return settings.image_api_key, "env"
    return None, None


async def is_configured() -> bool:
    key, _ = await resolve_key()
    return bool(key)


async def _require_key() -> str:
    key, _ = await resolve_key()
    if not key:
        raise SpriteStudioError(
            "Nenhuma chave de imagem configurada. Cole a chave em Admin -> Gerar sprites, "
            "ou defina BATTLE_IMAGE_API_KEY no .env do servidor."
        )
    return key


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


def _as_png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def _edit(client: httpx.AsyncClient, base: bytes, instruction: str, size: str) -> Image.Image:
    """Asks the model to change one thing about an image it is handed. This is
    the whole trick: identity comes from the reference, not from the words."""
    return await _post(
        client,
        "/images/edits",
        data={
            "model": settings.image_model,
            "prompt": (
                "Keep the exact same character, art style, colors, size and framing "
                f"as the reference image. Change only this: {instruction}. {STYLE_RULES}"
            ),
            "size": size,
            "background": "transparent",
            "n": "1",
        },
        files={"image": ("base.png", base, "image/png")},
    )


def _open_client(key: str) -> httpx.AsyncClient:
    try:
        return httpx.AsyncClient(
            base_url=settings.image_api_base.rstrip("/"),
            headers={"Authorization": f"Bearer {key}"},
            timeout=settings.image_timeout_seconds,
        )
    except httpx.InvalidURL as exc:
        # A typo in BATTLE_IMAGE_API_BASE would otherwise blow up as an opaque
        # 500 with no hint about which setting is wrong.
        raise SpriteStudioError(
            f"BATTLE_IMAGE_API_BASE inválido ({settings.image_api_base!r}): {exc}"
        ) from exc


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
    key = await _require_key()

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

    async with _open_client(key) as client:
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
            pose_instructions = poses[1:]
            logger.info("sprite studio: quadro 1 gerado do texto")
            step("quadro 1")

        reference_png = _as_png(frames[0])

        for index, pose in enumerate(pose_instructions, start=len(frames) + 1):
            frames.append(await _edit(client, reference_png, f"the pose becomes {pose}", size))
            logger.info("sprite studio: quadro %d gerado", index)
            step(f"quadro {index}")

        hit = fire = None
        if want_hit:
            hit = _as_png(
                await _edit(
                    client,
                    reference_png,
                    "the character is being hit and hurt right now: recoiling backwards, "
                    "face twisted in pain, eyes squeezed shut, arms thrown up defensively",
                    size,
                )
            )
            logger.info("sprite studio: imagem de dano gerada")
            step("pose de dano")
        if want_fire:
            fire = _as_png(
                await _edit(
                    client,
                    reference_png,
                    "the character is firing a big cannon shot right now: leaning into the "
                    "recoil, determined shouting expression, arms braced forward",
                    size,
                )
            )
            logger.info("sprite studio: imagem de disparo gerada")
            step("pose de ataque")

    sheet = compose_sheet(frames, columns=columns) if frames else None
    return StudioResult(sheet=sheet, hit=hit, fire=fire)


async def verify_key(candidate: str | None = None) -> str:
    """Checks a key against the provider without generating anything.

    Listing models costs nothing, so the panel can confirm a key works before
    the admin spends credits finding out that it does not.
    """
    key = candidate or await _require_key()
    async with _open_client(key) as client:
        try:
            response = await client.get("/models")
        except httpx.HTTPError as exc:
            raise SpriteStudioError(f"Não foi possível falar com a API de imagem: {exc}") from exc
        if response.status_code >= 400:
            raise SpriteStudioError(_explain(response))
    return "Chave aceita pela API."
