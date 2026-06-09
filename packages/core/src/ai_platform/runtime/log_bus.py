"""API-side fan-out for live worker → UI log streams.

This is **not** the worker's publish path — workers reach the API by
POSTing to `/jobs/{id}/logs` (see `WorkerLogger`). The router handler
calls `LogBus.publish` here, which broadcasts to every active SSE
subscriber for that `job_id`. One POST in, N streams out.

Per-process and in-memory by design: there's exactly one API process
in the current deploy shape, so a single shared bus is enough. When
we go multi-instance (e.g. several API workers behind a load balancer),
swap the implementation for Redis pub/sub behind the same `publish`
/ `subscribe` surface — every consumer here would keep working.

`LogEntry` is also re-exported and used by `WorkerLogger` as the wire
shape; its fields match the `POST /jobs/{id}/logs` body.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncIterator, Literal, Optional

from pydantic import BaseModel, Field

from ai_platform.utilities.time import utc_now


LogLevel = Literal["info", "warning", "error", "debug"]


class LogEntry(BaseModel):
    """Single log record emitted by the worker for one job."""
    job_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    level: LogLevel = "info"
    message: str
    stage: Optional[str] = None  # which graph node emitted it (when known)
    source: Optional[str] = None  # free-form origin tag (e.g. "worker", "tool:validate_latex")


_QUEUE_MAX = 256  # per-subscriber backpressure cap


class LogBus:
    """Per-job in-memory broadcaster.

    Subscribers receive a fresh `asyncio.Queue` and read with a normal
    async for. When the queue is full (slow consumer), new entries are
    dropped on the floor — logs are best-effort.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[LogEntry]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, entry: LogEntry) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(entry.job_id, ()))
        for q in queues:
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                # Drop — slow consumer, don't block publish.
                pass

    async def subscribe(self, job_id: str) -> AsyncIterator[LogEntry]:
        queue: asyncio.Queue[LogEntry] = asyncio.Queue(maxsize=_QUEUE_MAX)
        async with self._lock:
            self._subscribers.setdefault(job_id, []).append(queue)
        try:
            while True:
                entry = await queue.get()
                yield entry
        finally:
            async with self._lock:
                queues = self._subscribers.get(job_id, [])
                if queue in queues:
                    queues.remove(queue)
                if not queues and job_id in self._subscribers:
                    del self._subscribers[job_id]


_log_bus: Optional[LogBus] = None


def get_log_bus() -> LogBus:
    """Process-wide singleton accessor — same pattern as the rest of
    `runtime/registry`. Constructed lazily so test code can override
    via FastAPI dependency injection without booting the whole
    platform.
    """
    global _log_bus
    if _log_bus is None:
        _log_bus = LogBus()
    return _log_bus


