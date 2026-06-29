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

**Producer enqueues by NAME, never imports the consumer (issue #72).**
The API is the *producer*; the `run_job` task body lives in the worker
package (`ai_platform.entrypoints.celery_app`), which is **absent from
the api image** (api = api + core). So `enqueue` must not
`import … celery_app` — that `ModuleNotFoundError` was swallowed by the
best-effort enqueue and every job hung PENDING. Instead the producer
builds its own Celery app from `CELERY_BROKER_URL` and publishes by task
name with `app.send_task("run_job", …)` — no consumer import needed. The
producer app is built lazily + once so importing this module (or running
`COMPUTE=poll`) never requires `CELERY_BROKER_URL`.
"""
from __future__ import annotations

import os
from typing import Callable

from kombu.exceptions import OperationalError

from ai_platform.compute.base import EnqueueUnavailable
from ai_platform.jobs.execution_policy import JobExecution
from ai_platform.jobs.graph_execution import GraphJobExecutor
from ai_platform.jobs.runtimes import DEFAULT_RUNTIME

# The task is published by this name; the worker registers it with the same
# name (`@app.task(name="run_job")`). Centralised so producer + consumer can't
# drift, exactly like `celery_queue_for_runtime` for the queue.
RUN_JOB_TASK_NAME = "run_job"


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
        # Lazily-built producer Celery app (publishes by task name). Built on
        # first enqueue so constructing the backend never needs the broker URL.
        self._producer = None

    def _producer_app(self):
        """The producer-side Celery app: built from `CELERY_BROKER_URL`, used
        only to `send_task` by name. Cached so the broker connection pool is
        reused across submits. Crucially it imports nothing from the worker
        package, so it works in the split api image (issue #72)."""
        if self._producer is None:
            from celery import Celery

            self._producer = Celery(
                "ai-platform-producer", broker=os.environ["CELERY_BROKER_URL"]
            )
        return self._producer

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
        queue = celery_queue_for_runtime(self._runtime_for(job_id))
        try:
            self._producer_app().send_task(
                RUN_JOB_TASK_NAME, args=[job_id], queue=queue
            )
        except (OperationalError, ConnectionError) as exc:
            # Broker transiently unavailable (down / restarting). Surface it as
            # the platform's transient signal so the API leaves the job PENDING
            # for the reconciler — NOT a 500, and NOT a silent swallow of a
            # producer misconfig. Any *other* error (missing CELERY_BROKER_URL,
            # routing/serialisation/import error) propagates raw and must show
            # up — it can never hide as a permanent PENDING again (issue #72).
            raise EnqueueUnavailable(str(exc)) from exc

    def start_worker(self, **_kwargs) -> None:
        raise NotImplementedError(
            "CeleryComputeBackend has its own worker entrypoint. Run "
            "`celery -A ai_platform.entrypoints.celery_app worker`, not "
            "`python -m ai_platform.entrypoints.worker`."
        )
