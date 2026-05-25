"""Compute backend selection — `COMPUTE=poll|thread|celery` (default poll)."""
from __future__ import annotations

import os

from ai_platform.compute.base import ComputeBackend
from ai_platform.jobs.execution_policy import JobExecution
from ai_platform.jobs.graph_execution import GraphJobExecutor


def bootstrap_compute(
    executor: GraphJobExecutor,
    job_definitions: dict[str, JobExecution],
) -> ComputeBackend:
    name = os.getenv("COMPUTE", "poll").lower()

    if name == "poll":
        from ai_platform.compute.poll import PollingComputeBackend
        return PollingComputeBackend(executor, job_definitions)

    if name == "thread":
        from ai_platform.compute.thread import ThreadComputeBackend
        max_workers = int(os.getenv("COMPUTE_THREAD_WORKERS", "4"))
        return ThreadComputeBackend(executor, job_definitions, max_workers=max_workers)

    if name == "celery":
        from ai_platform.compute.celery import CeleryComputeBackend
        return CeleryComputeBackend(executor, job_definitions)

    raise ValueError(
        f"Unknown COMPUTE={name!r}. Expected one of: poll, thread, celery."
    )
