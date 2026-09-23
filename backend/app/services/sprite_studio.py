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
from dataclasses import dataclass, field
from io import BytesIO
from typing import Callable

import httpx
from PIL import Image

from app.core.config import settings
from app.services import secret_store
from app.services.background_cutout import cut_out
from app.services.image_providers import ImageProvider, ImageProviderError, build, catalog
from app.services.sprite_sheet import SheetLayout, compose_rows

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


def _clean(image: Image.Image, provider: ImageProvider) -> Image.Image:
    """Drop a flat background the service left behind.

    Only OpenAI has a transparency switch; the others can only be asked in
    words and often answer with the character on a white card, which the arena
    shows as a white rectangle. The cutout starts from the border and spreads
    only through connected pixels, so a white character keeps its own whites.

    It runs for every provider, not just the ones without the flag: even a
    service that has one sometimes returns an opaque frame, and a drawing that
    already carries real transparency is left untouched.
    """
    try:
        cleaned, changed = cut_out(image)
    except Exception:  # noqa: BLE001 - a failed cutout must never lose the art
        logger.exception("não consegui recortar o fundo; usando a imagem como veio")
        return image
    if changed:
        logger.info("fundo plano removido (%s)", provider.label)
    return cleaned


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


def _cycle_instruction(pose: str, index: int, total: int, looping: bool) -> str:
    """A frame described as part of a movement instead of on its own.

    Asking for four unrelated poses gets four unrelated drawings, and playing
    them in order reads as a machine snapping between positions. Saying which
    frame this is, and that the movement is continuous, gets in-between
    positions -- a body caught mid-motion rather than posed.
    """
    where = f"frame {index} of {total}"
    flow = (
        "This is a continuous looping animation: the movement must flow "
        "smoothly and the last frame has to lead straight back into the first, "
        "with no jump."
        if looping
        else "This is a short one-off movement played from start to finish."
    )
    return _edit_instruction(
        f"this is {where} of one continuous movement. {flow} "
        f"The body is caught in the middle of moving, never standing still or "
        f"posing for the camera. In this frame: {pose}"
    )


@dataclass
class Gesture:
    """A short one-off movement the character does between loops.

    Each gesture becomes its own row of the sheet, so the game can play it once
    and hand the character back to the base loop: a blink, a hop, a tongue out.
    Without these a character repeats the same few frames forever, which is
    what makes it read as a machine.
    """

    name: str
    poses: list[str]
    #: Fraction of its own height the character rises while this plays. The
    #: sheet stands every frame on its feet, so a hop needs this to leave the
    #: floor.
    lift: float = 0.0
    #: How often it is picked relative to the others.
    weight: float = 1.0
    fps: int = 0


@dataclass
class StudioResult:
    """Everything one run produced: the sheet, its clips, the reaction stills."""

    sheet: SheetLayout | None
    hit: bytes | None
    fire: bytes | None
    #: What each row of the sheet is, in the shape the game reads.
    clips: list[dict] = field(default_factory=list)


async def generate_artwork(
    description: str,
    poses: list[str],
    base_image: bytes | None = None,
    want_hit: bool = False,
    want_fire: bool = False,
    columns: int = 0,
    size: str = DEFAULT_SIZE,
    gestures: list[Gesture] | None = None,
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
    gestures = [
        Gesture(
            name=g.name.strip() or f"gesto{i}",
            poses=[p.strip() for p in g.poses if p.strip()],
            lift=g.lift,
            weight=g.weight,
            fps=g.fps,
        )
        for i, g in enumerate(gestures or [], start=1)
    ]
    gestures = [g for g in gestures if g.poses]

    if base_image is None and not description.strip():
        raise SpriteStudioError("Descreva o personagem ou envie uma imagem base.")
    if not poses and not gestures and not want_hit and not want_fire:
        raise SpriteStudioError("Escolha pelo menos uma pose ou uma imagem de ação.")
    if gestures and not poses:
        raise SpriteStudioError(
            "Os gestos são intercalados com o movimento base, então o movimento "
            "base precisa de pelo menos uma pose."
        )

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
    total += sum(len(g.poses) for g in gestures)
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
            # An uploaded caricature can arrive on a white card too, and it
            # becomes every other frame's reference -- so clean it first or the
            # card is inherited by the whole sheet.
            frames.append(_clean(reference, provider))
            pose_instructions = poses
            step("caricatura enviada")
        else:
            first = _clean(
                await provider.generate(
                    client,
                    f"{description.strip()}. {STYLE_RULES}. Pose: {poses[0]}",
                    size,
                ),
                provider,
            )
            frames.append(first)
            pose_instructions = poses[1:]
            logger.info("sprite studio: quadro 1 gerado do texto")
            step("quadro 1")

        reference_png = _as_png(frames[0])

        for index, pose in enumerate(pose_instructions, start=len(frames) + 1):
            frames.append(
                _clean(
                    await provider.edit(
                        client,
                        reference_png,
                        _cycle_instruction(pose, index, len(poses), looping=True),
                        size,
                    ),
                    provider,
                )
            )
            logger.info("sprite studio: quadro %d gerado", index)
            step(f"quadro {index}")

        # Each gesture is its own row, so the game can play it once and go
        # back to the base loop instead of folding it into the cycle.
        gesture_rows: list[list[Image.Image]] = []
        for gesture in gestures:
            row: list[Image.Image] = []
            for position, pose in enumerate(gesture.poses, start=1):
                row.append(
                    _clean(
                        await provider.edit(
                            client,
                            reference_png,
                            _cycle_instruction(
                                pose, position, len(gesture.poses), looping=False
                            ),
                            size,
                        ),
                        provider,
                    )
                )
                logger.info("sprite studio: %s %d/%d", gesture.name, position, len(gesture.poses))
                step(f"{gesture.name} {position}/{len(gesture.poses)}")
            gesture_rows.append(row)

        hit = fire = None
        if want_hit:
            hit = _as_png(
                _clean(await provider.edit(
                    client,
                    reference_png,
                    _edit_instruction(
                        "the character is being hit and hurt right now: recoiling backwards, "
                        "face twisted in pain, eyes squeezed shut, arms thrown up defensively"
                    ),
                    size,
                ), provider)
            )
            logger.info("sprite studio: imagem de dano gerada")
            step("pose de dano")
        if want_fire:
            fire = _as_png(
                _clean(await provider.edit(
                    client,
                    reference_png,
                    _edit_instruction(
                        "the character is attacking right now: throwing a bomb with one arm "
                        "stretched out, leaning forward, determined shouting expression"
                    ),
                    size,
                ), provider)
            )
            logger.info("sprite studio: imagem de disparo gerada")
            step("pose de ataque")

    return _lay_out(frames, gestures, gesture_rows, columns, hit, fire)


def _lay_out(
    base: list[Image.Image],
    gestures: list[Gesture],
    gesture_rows: list[list[Image.Image]],
    columns: int,
    hit: bytes | None,
    fire: bytes | None,
) -> StudioResult:
    """Turns the finished frames into a sheet plus the clip list that reads it.

    Without gestures the base row is wrapped at whatever width the admin asked
    for, exactly as before. With gestures every clip owns a row, because a clip
    is addressed as "row r, first n frames" and that only holds if the rows
    line up.
    """
    if not base:
        return StudioResult(sheet=None, hit=hit, fire=fire)

    if not gesture_rows:
        sheet = compose_rows([base]) if columns <= 0 else _wrapped(base, columns)
        clips = [
            {"name": "base", "row": 0, "frames": min(len(base), sheet.columns), "kind": "idle"}
        ]
        # A wrapped base row spans several rows: the whole grid is one loop,
        # which is what a sheet without gestures always was. Saying so with no
        # clips at all keeps the old behaviour in the game.
        if sheet.rows > 1:
            clips = []
        return StudioResult(sheet=sheet, hit=hit, fire=fire, clips=clips)

    sheet = compose_rows([base, *gesture_rows])
    clips: list[dict] = [
        {"name": "base", "row": 0, "frames": len(base), "kind": "idle", "weight": 1}
    ]
    for index, gesture in enumerate(gestures, start=1):
        clip = {
            "name": gesture.name,
            "row": index,
            "frames": len(gesture_rows[index - 1]),
            "kind": "gesture",
            "weight": gesture.weight,
        }
        if gesture.fps > 0:
            clip["fps"] = gesture.fps
        if gesture.lift > 0:
            clip["lift"] = gesture.lift
        clips.append(clip)
    return StudioResult(sheet=sheet, hit=hit, fire=fire, clips=clips)


def _wrapped(frames: list[Image.Image], columns: int) -> SheetLayout:
    """The old layout: one long strip folded at `columns`."""
    rows = [frames[i : i + columns] for i in range(0, len(frames), columns)]
    return compose_rows(rows)


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
