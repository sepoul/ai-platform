"""Job logs router — live worker → UI log streaming.

Two endpoints:

- `POST /jobs/{job_id}/logs` — emit a log entry. Used by remote
  workers; in-process workers can call `log_bus.publish` directly.
- `GET /jobs/{job_id}/logs/stream` — Server-Sent Events stream of
  every log entry published for this job until the client disconnects.

Browser clients connect to this via the Next.js BFF
`/api/jobs/[jobId]/logs/stream`, which forwards the SSE response body
straight through.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ai_platform.runtime.log_bus import LogEntry, get_log_bus


router = APIRouter()


@router.post("/jobs/{job_id}/logs")
async def emit_log(job_id: str, body: LogEntry):
    # Trust the path parameter as the canonical job_id (don't let the
    # body silently override it).
    body = body.model_copy(update={"job_id": job_id})
    await get_log_bus().publish(body)
    return {"ok": True}


def _sse_event(entry: LogEntry) -> str:
    """Format one LogEntry as an SSE message."""
    payload = entry.model_dump_json()
    return f"data: {payload}\n\n"


@router.get("/jobs/{job_id}/logs/stream")
async def stream_logs(job_id: str, request: Request):
    bus = get_log_bus()

    async def event_source() -> AsyncIterator[str]:
        # Send a comment immediately so the browser EventSource fires
        # `onopen` even before any real log lands.
        yield ": connected\n\n"

        async for entry in bus.subscribe(job_id):
            if await request.is_disconnected():
                break
            yield _sse_event(entry)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx buffering if proxied
            "Connection": "keep-alive",
        },
    )


# Keep `asyncio` referenced even when we only use it transitively —
# avoids an unused-import warning if a future refactor leans on
# `asyncio.timeout` here.
_ = asyncio
_ = json
