import asyncio
import logging

from app.schemas.schemas import LiveEvent
from app.services.pipeline import game_pipeline

logger = logging.getLogger("event_queue")


class EventQueue:
    """Serializes live events per battle session so bursts of gifts (a
    rajada of 100 roses, dozens of viewers joining at once) never race each
    other into the DB, and so a slow WebSocket broadcast never blocks the
    provider ingest loop. One asyncio worker per active session -- cheap
    and plenty for a single-process deployment; swap the queue backing for
    Redis streams later if fanning out across processes."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}
        self._workers: dict[str, asyncio.Task] = {}

    def _ensure_worker(self, session_id: str) -> None:
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue(maxsize=5000)
        if session_id not in self._workers or self._workers[session_id].done():
            self._workers[session_id] = asyncio.create_task(self._worker(session_id))

    async def enqueue(self, session_id: str, event: LiveEvent) -> None:
        self._ensure_worker(session_id)
        queue = self._queues[session_id]
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("event queue full for session=%s, dropping oldest", session_id)
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            queue.put_nowait(event)

    def pending(self, session_id: str) -> int:
        q = self._queues.get(session_id)
        return q.qsize() if q else 0

    async def _worker(self, session_id: str) -> None:
        queue = self._queues[session_id]
        while True:
            event = await queue.get()
            try:
                await game_pipeline.handle_event(session_id, event)
            except Exception:
                logger.exception("failed processing event for session=%s", session_id)
            finally:
                queue.task_done()


event_queue = EventQueue()
