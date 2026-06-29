"""Celery compute backend.

Selected with `COMPUTE=celery`. The API calls `enqueue(job_id)` after
persisting the `JobRecord`; the actual work runs in
`ai_platform.entrypoints.celery_app:run_job`, started via
`celery -A ai_platform.entrypoints.celery_app worker`.

**Per-runtime routing (issue #66).** Prod deliberately splits runtimes
across worker pools with disjoint dependency stacks — `default`
(pydantic_ai: math_qa, math_notes) vs `crewai` (CrewAI:
math_conversation) — because the stacks can't share one interpreter
(otel-sdk pin conflict; see `ai_platform.jobs.runtimes`). So a single
Celery pool can't serve every runtime. `enqueue` routes each job to a
per-runtime queue (`celery_queue_for_runtime`) keyed off the job's
`runtime_selector` (resolved from the JobDefinition catalog); one
consumer per runtime registers only its own domains and consumes only
its own queue. This mirrors the two-poll-worker topology (`worker` /
`worker-crewai`).

The task import is lazy on purpose: importing `celery_app` at module
top-level would force the API process to bootstrap the workspace twice
and require `CELERY_BROKER_URL` even when `COMPUTE=poll`.
"""
from __future__ import annotations

from typing import Callable

from ai_platform.jobs.execution_policy import JobExecution
from ai_platform.jobs.graph_execution import GraphJobExecutor
from ai_platform.jobs.runtimes import DEFAULT_RUNTIME


def celery_queue_for_runtime(runtime: str) -> str:
    """Celery queue a given worker runtime produces to / consumes from.

    One queue per runtime so a consumer provisioned for one stack never
    receives a job it can't import. Centralised + trivial so the producer
    (`CeleryComputeBackend.enqueue`) and the consumer (`celery_app`) can't
    drift on the naming.
    """
    return f"runtime.{runtime}"


class CeleryComputeBackend:
    name = "celery"

    def __init__(
        self,
        executor: GraphJobExecutor,
        job_definitions: dict[str, JobExecution],
        *,
        runtime_for_job_type: Callable[[str], str] | None = None,
    ):
        self._executor = executor
        self._job_definitions = job_definitions
        # job_type -> runtime resolver, supplied by the API from the
        # JobDefinition catalog. None → every job routes to the default
        # runtime's queue (single-pool / test fallback).
        self._runtime_for_job_type = runtime_for_job_type

    def _runtime_for(self, job_id: str) -> str:
        if self._runtime_for_job_type is None:
            return DEFAULT_RUNTIME
        try:
            record = self._executor.repo.get(job_id)
            return self._runtime_for_job_type(record.spec.job_type)
        except Exception:
            # Unknown / unresolvable runtime → default queue. The default
            # consumer fails fast with "Unknown job type" if it can't serve
            # the job, a clearer signal than a silent drop on an unknown
            # queue no worker consumes.
            return DEFAULT_RUNTIME

    def enqueue(self, job_id: str) -> None:
        from ai_platform.entrypoints.celery_app import run_job

        queue = celery_queue_for_runtime(self._runtime_for(job_id))
        run_job.apply_async(args=[job_id], queue=queue)

    def start_worker(self, **_kwargs) -> None:
        raise NotImplementedError(
            "CeleryComputeBackend has its own worker entrypoint. Run "
            "`celery -A ai_platform.entrypoints.celery_app worker`, not "
            "`python -m ai_platform.entrypoints.worker`."
        )
