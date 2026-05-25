"""In-process thread-pool compute backend.

`enqueue` schedules the job on a `ThreadPoolExecutor` running inside
the API process. There is no separate worker — the API is its own
worker. Selected with `COMPUTE=thread`.

Why ship this when Celery is the eventual target?

1. It proves the `ComputeBackend` seam works for a non-poll backend
   without a broker dependency.
2. It's a useful single-machine dev mode: no second process to start,
   jobs run with sub-second latency.
3. It makes the trade-offs of a "real" queue concrete — work in
   flight is *lost on restart* because the queue is RAM-only and
   nothing reclaims `RUNNING` records on boot. That's exactly the
   problem Celery + a broker solves, which makes the case for it.

Not a production answer for multi-instance APIs.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from ai_platform.jobs.execution_policy import JobExecution
from ai_platform.jobs.graph_execution import GraphJobExecutor

logger = logging.getLogger(__name__)


class ThreadComputeBackend:
    name = "thread"

    def __init__(
        self,
        executor: GraphJobExecutor,
        job_definitions: dict[str, JobExecution],
        max_workers: int = 4,
    ):
        self._executor = executor
        self._job_definitions = job_definitions
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="job"
        )
        self._worker_id = f"thread-{id(self) & 0xFFFF:x}"

    def enqueue(self, job_id: str) -> None:
        # We don't pin to job_id because `_run_one_job` calls
        # `claim_next_pending` which is the existing race-safe path.
        # Submitting a tick per enqueue means a thread is reserved per
        # submitted job (good for backpressure on the pool).
        self._pool.submit(self._tick)

    def _tick(self) -> None:
        # Lazy import: the worker loop pulls the graph engine. Thread compute
        # runs jobs in-process, so this backend is not for the engine-free API.
        from ai_platform.jobs.worker_loop import _run_one_job

        try:
            _run_one_job(self._executor, self._job_definitions, self._worker_id)
        except Exception:
            logger.exception("ThreadComputeBackend: job execution crashed")

    def start_worker(self, **_kwargs) -> None:
        raise NotImplementedError(
            "ThreadComputeBackend runs in-process — do not start a separate "
            "worker. Use COMPUTE=poll if you want a standalone worker."
        )

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)
