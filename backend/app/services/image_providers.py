"""Where the drawings come from.

Three services can produce the art, and they disagree about almost everything:
how the key travels, whether an edit is a multipart upload or a JSON field,
what the response looks like, and whether "transparent background" is a flag
or a sentence in the prompt. Each one is wrapped here so the studio above only
ever asks for two things -- draw this, and change that one thing about this
picture -- and never learns which service answered.

Adding a fourth provider means adding a class here and a name to PROVIDERS;
nothing in the studio or the panel has to know about it.
"""

from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from io import BytesIO

import httpx
from PIL import Image

from app.core.config import settings

logger = logging.getLogger("image_providers")


class ImageProviderError(RuntimeError):
    """Something the admin can act on -- shown as-is in the panel."""


def _decode_b64(data: str) -> Image.Image:
    try:
        return Image.open(BytesIO(base64.b64decode(data))).convert("RGBA")
    except Exception as exc:  # noqa: BLE001 - any unreadable payload is one problem
        raise ImageProviderError("A API devolveu uma imagem que não consegui ler.") from exc


class ImageProvider(ABC):
    """One image service, reduced to draw-and-edit."""

    #: Shown in the panel.
    label: str = ""
    #: Frame size used when the admin has not chosen one. Providers disagree
    #: about what they accept, so each one names its own.
    default_size: str = "1024x1536"
    #: True when the service has a real transparency switch. The ones without
    #: it can only be asked nicely in the prompt, and often answer with a
    #: white rectangle -- which the panel warns about rather than hiding.
    supports_transparency: bool = False

    def __init__(self, key: str) -> None:
        self.key = key

    @abstractmethod
    async def generate(self, client: httpx.AsyncClient, prompt: str, size: str) -> Image.Image:
        """Draw from words alone."""

    @abstractmethod
    async def edit(
        self, client: httpx.AsyncClient, reference_png: bytes, instruction: str, size: str
    ) -> Image.Image:
        """Change one thing about a picture it is handed.

        This is what keeps a sprite sheet consistent: identity comes from the
        reference image, and the instruction only says what moved.
        """

    @abstractmethod
    async def verify(self, client: httpx.AsyncClient) -> str:
        """Confirm the key works without spending credits on a drawing."""

    @abstractmethod
    def open_client(self) -> httpx.AsyncClient:
        ...

    # -- shared helpers ---------------------------------------------------

    def _client(self, base_url: str, headers: dict[str, str]) -> httpx.AsyncClient:
        try:
            return httpx.AsyncClient(
                base_url=base_url.rstrip("/"),
                headers=headers,
                timeout=settings.image_timeout_seconds,
            )
        except httpx.InvalidURL as exc:
            raise ImageProviderError(f"Endereço da API inválido ({base_url!r}): {exc}") from exc

    def _explain(self, response: httpx.Response) -> str:
        """Surface the service's own message. A generic 'deu erro' would leave
        the admin guessing between a bad key, no credit and a rejected prompt."""
        detail = None
        try:
            body = response.json()
            detail = (
                (body.get("error") or {}).get("message")
                if isinstance(body.get("error"), dict)
                else body.get("error")
            ) or body.get("message")
        except Exception:  # noqa: BLE001 - a non-JSON body is still useful
            detail = None
        detail = detail or response.text[:300]
        if response.status_code in (401, 403):
            return f"A chave foi recusada ({response.status_code}): {detail}"
        if response.status_code == 429:
            return f"Limite da API atingido: {detail}"
        return f"A API respondeu {response.status_code}: {detail}"

    async def _post(self, client: httpx.AsyncClient, path: str, **kwargs) -> dict:
        try:
            response = await client.post(path, **kwargs)
        except httpx.HTTPError as exc:
            raise ImageProviderError(f"Não foi possível falar com a API: {exc}") from exc
        if response.status_code >= 400:
            raise ImageProviderError(self._explain(response))
        try:
            return response.json()
        except ValueError as exc:
            raise ImageProviderError("A API devolveu uma resposta que não é JSON.") from exc


# ---------------------------------------------------------------------------
# OpenAI (gpt-image-1) and a multipart edit endpoint
# ---------------------------------------------------------------------------


class OpenAIImageProvider(ImageProvider):
    label = "OpenAI (gpt-image-1)"
    default_size = "1024x1536"
    supports_transparency = True

    def open_client(self) -> httpx.AsyncClient:
        return self._client(settings.image_api_base, {"Authorization": f"Bearer {self.key}"})

    def _first_image(self, payload: dict) -> Image.Image:
        try:
            return _decode_b64(payload["data"][0]["b64_json"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ImageProviderError(f"Resposta inesperada da API: {payload}") from exc

    async def generate(self, client: httpx.AsyncClient, prompt: str, size: str) -> Image.Image:
        payload = await self._post(
            client,
            "/images/generations",
            json={
                "model": settings.image_model,
                "prompt": prompt,
                "size": size,
                "output_format": "png",
                "n": 1,
            },
        )
        return self._first_image(payload)

    async def edit(
        self, client: httpx.AsyncClient, reference_png: bytes, instruction: str, size: str
    ) -> Image.Image:
        payload = await self._post(
            client,
            "/images/edits",
            data={
                "model": settings.image_model,
                "prompt": instruction,
                "size": size,
                "n": "1",
            },
            files={"image": ("base.png", reference_png, "image/png")},
        )
        return self._first_image(payload)

    async def verify(self, client: httpx.AsyncClient) -> str:
        try:
            response = await client.get("/models")
        except httpx.HTTPError as exc:
            raise ImageProviderError(f"Não foi possível falar com a API: {exc}") from exc
        if response.status_code >= 400:
            raise ImageProviderError(self._explain(response))
        return "Chave aceita pela OpenAI."


# ---------------------------------------------------------------------------
# Google Gemini: one endpoint for both, image in and image out as inline data
# ---------------------------------------------------------------------------


class GeminiImageProvider(ImageProvider):
    """Gemini draws and edits through the same generateContent call.

    It has no size parameter and no transparency switch, so the frame size is
    whatever the model returns and transparency has to be asked for in words.
    The sheet composer normalises the cells afterwards, which is what keeps
    frames of slightly different sizes from tearing the animation apart.
    """

    label = "Google Gemini (gemini-2.5-flash-image)"
    default_size = "1024x1536"
    supports_transparency = False

    def open_client(self) -> httpx.AsyncClient:
        # The key goes in a header rather than the query string so it does not
        # end up in proxy logs.
        return self._client(
            settings.gemini_api_base,
            {"x-goog-api-key": self.key, "Content-Type": "application/json"},
        )

    def _first_image(self, payload: dict) -> Image.Image:
        candidates = payload.get("candidates") or []
        for candidate in candidates:
            for part in (candidate.get("content") or {}).get("parts") or []:
                # REST answers in camelCase; the SDKs use snake_case. Accept both.
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return _decode_b64(inline["data"])

        # A refusal comes back as text with no image at all, and its wording is
        # the only clue about what the model objected to.
        reason = None
        for candidate in candidates:
            reason = candidate.get("finishReason") or reason
            for part in (candidate.get("content") or {}).get("parts") or []:
                if part.get("text"):
                    reason = part["text"][:300]
        blocked = (payload.get("promptFeedback") or {}).get("blockReason")
        raise ImageProviderError(
            f"O Gemini não devolveu imagem. {blocked or reason or payload}"
        )

    async def _generate_content(self, client: httpx.AsyncClient, parts: list[dict]) -> Image.Image:
        payload = await self._post(
            client,
            f"/models/{settings.gemini_image_model}:generateContent",
            json={
                "contents": [{"parts": parts}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            },
        )
        return self._first_image(payload)

    async def generate(self, client: httpx.AsyncClient, prompt: str, size: str) -> Image.Image:
        return await self._generate_content(client, [{"text": prompt}])

    async def edit(
        self, client: httpx.AsyncClient, reference_png: bytes, instruction: str, size: str
    ) -> Image.Image:
        return await self._generate_content(
            client,
            [
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": base64.b64encode(reference_png).decode(),
                    }
                },
                {"text": instruction},
            ],
        )

    async def verify(self, client: httpx.AsyncClient) -> str:
        try:
            response = await client.get("/models")
        except httpx.HTTPError as exc:
            raise ImageProviderError(f"Não foi possível falar com a API: {exc}") from exc
        if response.status_code >= 400:
            raise ImageProviderError(self._explain(response))
        return "Chave aceita pelo Gemini."


# ---------------------------------------------------------------------------
# AIsa: OpenAI-shaped images endpoint, but edits take reference URLs in JSON
# ---------------------------------------------------------------------------


class AisaImageProvider(ImageProvider):
    """AIsa speaks the OpenAI Images format with two differences that matter.

    An edit is not a multipart upload to /images/edits: the reference goes in
    the same /images/generations call, as an ``image`` array. And the upstream
    model refuses anything under ~3.7 megapixels, so the portrait default here
    is much larger than OpenAI's.
    """

    label = "AIsa (Seedream)"
    # 1600x2400 = 3,840,000 px, just over the upstream minimum of 3,686,400.
    default_size = "1600x2400"
    supports_transparency = False

    MIN_PIXELS = 3_686_400

    def open_client(self) -> httpx.AsyncClient:
        return self._client(settings.aisa_api_base, {"Authorization": f"Bearer {self.key}"})

    def _check_size(self, size: str) -> str:
        try:
            width, height = (int(part) for part in size.lower().split("x", 1))
        except ValueError:
            return self.default_size
        if width * height < self.MIN_PIXELS:
            logger.info(
                "AIsa exige ao menos %s px; %s seria recusado, usando %s",
                self.MIN_PIXELS,
                size,
                self.default_size,
            )
            return self.default_size
        return size

    async def _first_image(self, client: httpx.AsyncClient, payload: dict) -> Image.Image:
        try:
            first = payload["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ImageProviderError(f"Resposta inesperada da API: {payload}") from exc

        if first.get("b64_json"):
            return _decode_b64(first["b64_json"])
        if first.get("url"):
            # This provider may answer with a link instead of bytes, so fetch
            # it here rather than making the studio care which it got.
            try:
                response = await client.get(first["url"], timeout=60.0)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ImageProviderError(f"Não consegui baixar a imagem gerada: {exc}") from exc
            return Image.open(BytesIO(response.content)).convert("RGBA")
        raise ImageProviderError(f"Resposta sem imagem: {payload}")

    async def generate(self, client: httpx.AsyncClient, prompt: str, size: str) -> Image.Image:
        payload = await self._post(
            client,
            "/images/generations",
            json={
                "model": settings.aisa_image_model,
                "prompt": prompt,
                "size": self._check_size(size),
                "n": 1,
                "response_format": "b64_json",
            },
        )
        return await self._first_image(client, payload)

    async def edit(
        self, client: httpx.AsyncClient, reference_png: bytes, instruction: str, size: str
    ) -> Image.Image:
        reference = "data:image/png;base64," + base64.b64encode(reference_png).decode()
        try:
            payload = await self._post(
                client,
                "/images/generations",
                json={
                    "model": settings.aisa_image_model,
                    "prompt": instruction,
                    # Seedream takes its references here instead of on a
                    # separate edits endpoint.
                    "image": [reference],
                    "size": self._check_size(size),
                    "n": 1,
                    "response_format": "b64_json",
                },
            )
        except ImageProviderError as exc:
            # The documented field takes image URLs. Whether it also takes an
            # inline data URI is the one thing that could not be confirmed
            # without an account, so say so plainly instead of leaving the
            # admin staring at a raw 400.
            raise ImageProviderError(
                f"{exc} — se a AIsa recusou a imagem de referência, este provedor pode "
                "exigir uma URL pública em vez da imagem embutida. Gere com a OpenAI ou o "
                "Gemini, ou envie a caricatura pronta em 'Carregar caricatura'."
            ) from exc
        return await self._first_image(client, payload)

    async def verify(self, client: httpx.AsyncClient) -> str:
        try:
            response = await client.get("/models")
        except httpx.HTTPError as exc:
            raise ImageProviderError(f"Não foi possível falar com a API: {exc}") from exc
        if response.status_code >= 400:
            raise ImageProviderError(self._explain(response))
        return "Chave aceita pela AIsa."


PROVIDERS: dict[str, type[ImageProvider]] = {
    "openai": OpenAIImageProvider,
    "gemini": GeminiImageProvider,
    "aisa": AisaImageProvider,
}


def build(name: str, key: str) -> ImageProvider:
    provider = PROVIDERS.get((name or "").lower())
    if provider is None:
        raise ImageProviderError(
            f"Provedor de imagem desconhecido: {name!r}. "
            f"Use um destes: {', '.join(PROVIDERS)}."
        )
    return provider(key)


def catalog() -> list[dict]:
    """What the panel offers, straight from the classes above."""
    return [
        {
            "id": name,
            "label": cls.label,
            "default_size": cls.default_size,
            "supports_transparency": cls.supports_transparency,
        }
        for name, cls in PROVIDERS.items()
    ]
