"""Convenience wrapper for emitting log entries from worker code.

Graph nodes get a `WorkerLogger` bound to the current `job_id` (and
optionally a stage label) so they can call `.info("...")` / `.error("...")`
without juggling job ids each time.

The logger always crosses to the API via `POST /jobs/{id}/logs`,
even when the worker happens to share a process with the API. The
HTTP hop is what lets workers run as a separate process (the
default with `scripts/worker.sh`) without losing logs to a different
in-memory `LogBus`. Configured via `PLATFORM_API_URL`
(default `http://127.0.0.1:8000`).

Logs are best-effort: any transport error (API down, timeout,
connection refused) is swallowed so a worker never fails because of
a missing log line.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from ai_platform.runtime.log_bus import LogEntry, LogLevel


_DEFAULT_API_URL = "http://127.0.0.1:8000"
_TIMEOUT_SECONDS = 2.0
_logger = logging.getLogger(__name__)


def _api_url() -> str:
    return os.getenv("PLATFORM_API_URL", _DEFAULT_API_URL).rstrip("/")


class WorkerLogger:
    def __init__(
        self,
        job_id: str,
        stage: Optional[str] = None,
        source: str = "worker",
    ) -> None:
        self.job_id = job_id
        self.stage = stage
        self.source = source

    async def emit(self, message: str, *, level: LogLevel = "info") -> None:
        entry = LogEntry(
            job_id=self.job_id,
            level=level,
            message=message,
            stage=self.stage,
            source=self.source,
        )
        url = f"{_api_url()}/jobs/{self.job_id}/logs"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                await client.post(url, json=entry.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001 — best-effort
            # Don't take down the worker for a missing log. Surface
            # the cause once at debug level for diagnosability.
            _logger.debug("WorkerLogger drop: %s (%s)", message, exc)

    # Convenience wrappers — same names as stdlib logger so node
    # authors fall into the right ergonomic by default.
    async def info(self, message: str) -> None:
        await self.emit(message, level="info")

    async def warning(self, message: str) -> None:
        await self.emit(message, level="warning")

    async def error(self, message: str) -> None:
        await self.emit(message, level="error")

    async def debug(self, message: str) -> None:
        await self.emit(message, level="debug")

    def for_stage(self, stage: str) -> "WorkerLogger":
        """Return a child logger tagged with the given stage label."""
        return WorkerLogger(job_id=self.job_id, stage=stage, source=self.source)


class NullLogger(WorkerLogger):
    """Drop-everything logger for contexts without a `job_id` (tests,
    standalone scripts, deps_factory not connected to a runner). Lets
    node code call `await ctx.deps.logger.info(...)` without guarding.
    """

    def __init__(self) -> None:  # noqa: D401 — no super, by design
        self.job_id = ""
        self.stage = None
        self.source = "null"

    async def emit(self, message: str, *, level: LogLevel = "info") -> None:
        return None

    def for_stage(self, stage: str) -> "WorkerLogger":  # type: ignore[override]
        return self
