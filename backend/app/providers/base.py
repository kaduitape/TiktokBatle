from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from app.schemas.schemas import LiveEvent

EventHandler = Callable[[str, LiveEvent], Awaitable[None]]


class LiveEventProvider(ABC):
    """The Game Engine never talks to TikTok directly (spec section 47).
    Any source of interactions -- a real TikTok LIVE connection, the admin
    simulator, a future platform -- implements this interface and produces
    the same standard LiveEvent shape (section 48), so the rest of the
    pipeline is 100% provider-agnostic."""

    def __init__(self) -> None:
        self._handler: EventHandler | None = None

    def on_event(self, handler: EventHandler) -> None:
        self._handler = handler

    async def emit(self, session_id: str, event: LiveEvent) -> None:
        if self._handler is None:
            raise RuntimeError("no event handler registered on provider")
        await self._handler(session_id, event)

    @abstractmethod
    async def start(self, session_id: str, **kwargs) -> None: ...

    @abstractmethod
    async def stop(self, session_id: str) -> None: ...
