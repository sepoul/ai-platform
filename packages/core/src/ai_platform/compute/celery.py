"""Celery compute backend.

Selected with `COMPUTE=celery`. The API calls `enqueue(job_id)` after
persisting the `JobRecord`; the actual work runs in
`mathapp.entrypoints.celery_app:run_job`, started via
`celery -A mathapp.entrypoints.celery_app worker`.

The task import is lazy on purpose: importing `celery_app` at module
top-level would force the API process to bootstrap the workspace twice
and require `CELERY_BROKER_URL` even when `COMPUTE=poll`.
"""
from __future__ import annotations

from ai_platform.jobs.execution_policy import JobExecution
from ai_platform.jobs.graph_execution import GraphJobExecutor


class CeleryComputeBackend:
    name = "celery"

    def __init__(
        self,
        executor: GraphJobExecutor,
        job_definitions: dict[str, JobExecution],
    ):
        self._executor = executor
        self._job_definitions = job_definitions

    def enqueue(self, job_id: str) -> None:
        from mathapp.entrypoints.celery_app import run_job

        run_job.delay(job_id)

    def start_worker(self, **_kwargs) -> None:
        raise NotImplementedError(
            "CeleryComputeBackend has its own worker entrypoint. Run "
            "`celery -A mathapp.entrypoints.celery_app worker`, not "
            "`python -m mathapp.entrypoints.worker`."
        )
