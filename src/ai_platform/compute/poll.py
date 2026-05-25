"""Polling compute backend.

The original (and only) compute model: workers loop on
`claim_next_pending`, the API does nothing special on submit. Selected
when `COMPUTE=poll` (the default) — `scripts/worker.sh` runs the loop.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from ai_platform.jobs.execution_policy import JobExecution
from ai_platform.jobs.graph_execution import GraphJobExecutor
from ai_platform.jobs.worker_loop import _run_one_job

logger = logging.getLogger(__name__)


class PollingComputeBackend:
    name = "poll"

    def __init__(
        self,
        executor: GraphJobExecutor,
        job_definitions: dict[str, JobExecution],
        default_interval_s: int = 5,
    ):
        self._executor = executor
        self._job_definitions = job_definitions
        self._default_interval_s = default_interval_s

    def enqueue(self, job_id: str) -> None:
        # No-op: workers discover new records via `claim_next_pending`.
        # Kept as a debug log so the seam is visible in traces.
        logger.debug("poll: enqueue(%s) is a no-op", job_id)

    def start_worker(
        self,
        *,
        worker_id: str,
        interval_s: int | None = None,
        once: bool = False,
        should_stop: Callable[[], bool] = lambda: False,
        max_job_age_s: float | None = None,
    ) -> None:
        interval = interval_s if interval_s is not None else self._default_interval_s
        logger.info(
            "Worker %s starting (poll interval=%ds, once=%s, max_job_age=%s)",
            worker_id, interval, once,
            f"{max_job_age_s:.0f}s" if max_job_age_s is not None else "unlimited",
        )

        while not should_stop():
            did_work = _run_one_job(
                self._executor, self._job_definitions, worker_id,
                max_job_age_s=max_job_age_s,
            )

            if once:
                if not did_work:
                    logger.info("No jobs found. Exiting (--once).")
                break

            if not did_work:
                logger.debug("No pending jobs, sleeping %ds…", interval)
                time.sleep(interval)

        logger.info("Worker %s stopped", worker_id)
