"""Platform job-run endpoints — generic dispatch by job_type.

Built as a factory so the submit body reflects the discriminated union of
every registered `JobControl.submit_input_type`. The TS client narrows
on `job_type` for both the request and the response.
"""
# NOTE: deliberately no `from __future__ import annotations` — FastAPI
# needs to resolve the dynamically-built `RunSubmitRequest` body annotation
# at runtime, which requires real (non-stringified) annotations.

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import RootModel

from ai_platform.runtime.registry import get_compute, get_executor, get_job_controls
from ai_platform.api.schemas.jobs import (
    RunSubmitResponse,
    build_review_request_model,
    build_run_submit_request_model,
)
from ai_platform.compute.base import ComputeBackend
from ai_platform.jobs.execution_policy import JobControl
from ai_platform.jobs.graph_execution import GraphJobExecutor
from ai_platform.workspace.storage.structured.job_repository import JobStatus

logger = logging.getLogger(__name__)


def _enqueue_best_effort(compute: ComputeBackend, job_id: str) -> None:
    """Hand a job to the compute backend without ever failing the submit on a
    broker hiccup (issue #67).

    The `JobRecord` is already durably persisted as PENDING before this runs,
    so the row is never lost. For a push backend (Celery) the enqueue can still
    raise — Redis down, restarting — and an unguarded call would 500 the submit
    *after* the orphan row exists. Instead we log and return: the job stays
    PENDING and the reconciler (`reconcile_pending_jobs`) re-`enqueue`s it once
    it ages past the grace window. This mirrors poll's guarantee (the repo is
    the queue) for push backends; poll's own `enqueue` is a no-op and never
    reaches the except.
    """
    try:
        compute.enqueue(job_id)
    except Exception:
        logger.warning(
            "enqueue(%s) failed (broker unavailable?); job stays PENDING and "
            "will be re-driven by the reconciler",
            job_id,
            exc_info=True,
        )


def make_job_runs_router(jobs: dict[str, JobControl]) -> APIRouter:
    router = APIRouter()

    RunSubmitRequest = build_run_submit_request_model(
        [j.submit_input_type for j in jobs.values()]
    )
    ReviewRequest = build_review_request_model(
        [g.review_type for j in jobs.values() for g in j.gates]
    )

    @router.post("/jobs/runs/submit", response_model=RunSubmitResponse)
    def submit_job_run(
        body: RunSubmitRequest,
        executor: GraphJobExecutor = Depends(get_executor),
        jobs_dep: dict[str, JobControl] = Depends(get_job_controls),
        compute: ComputeBackend = Depends(get_compute),
    ):
        inner = body.root if isinstance(body, RootModel) else body
        params = inner.model_dump(exclude={"job_type"})
        job_def = jobs_dep[inner.job_type]

        record = executor.submit_graph_job(
            job_type=job_def.name,
            graph_ref=job_def.label,
            initial_state={},
            deps_payload=params,
            created_by=params.get("created_by"),
        )
        _enqueue_best_effort(compute, str(record.spec.job_id))
        return RunSubmitResponse(job_id=str(record.spec.job_id), status=record.state.status.value)

    @router.post("/jobs/{job_id}/review", response_model=RunSubmitResponse)
    def review_job(
        job_id: str,
        body: ReviewRequest,
        executor: GraphJobExecutor = Depends(get_executor),
        jobs_dep: dict[str, JobControl] = Depends(get_job_controls),
        compute: ComputeBackend = Depends(get_compute),
    ):
        try:
            record = executor.repo.get(job_id)
        except Exception:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        job_def = jobs_dep.get(record.spec.job_type)
        if not job_def:
            raise HTTPException(
                status_code=400,
                detail=f"Job type '{record.spec.job_type}' has no registered definition",
            )

        checkpoint = executor.load_checkpoint(job_id)
        if not checkpoint:
            raise HTTPException(status_code=409, detail=f"Job {job_id} has no checkpoint to resume from")

        gated_node = checkpoint.gated_node
        if not gated_node:
            raise HTTPException(status_code=409, detail=f"Job {job_id} has no pending gate")

        gate = job_def.gate_for(gated_node)
        if not gate:
            raise HTTPException(
                status_code=409,
                detail=f"Node '{gated_node}' is not a human gate in job type '{job_def.name}'",
            )

        review = body.root if isinstance(body, RootModel) else body
        if not isinstance(review, gate.review_type):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Review body shape does not match gate '{gated_node}': "
                    f"expected {gate.review_type.__name__}, got {type(review).__name__}"
                ),
            )

        # Review-as-data: the API validates the body against the gate's
        # schema and stores the raw payload on the record. It does NOT
        # deserialize/merge the execution state model — the worker does
        # that on resume (see job_runner). Keeps the API engine-free.
        record.state.pending_review = review.model_dump(mode="json")
        record.state.status = JobStatus.PENDING
        record.state.waiting_for = None
        record._bump()
        executor.repo.put(record)

        # Resuming is a "submit moment" too — queue-based backends
        # need to re-deliver this job_id to a worker. Best-effort like submit:
        # a broker hiccup here leaves the row PENDING for the reconciler, not a
        # 500 with the job stranded mid-resume (issue #67).
        _enqueue_best_effort(compute, str(record.spec.job_id))

        return RunSubmitResponse(job_id=str(record.spec.job_id), status=record.state.status.value)

    # Terminal states a job can already be in — nothing to cancel.
    _TERMINAL = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)

    @router.post("/jobs/{job_id}/cancel", response_model=RunSubmitResponse)
    def cancel_job(
        job_id: str,
        executor: GraphJobExecutor = Depends(get_executor),
    ):
        """Operator/recovery endpoint: force a job to the terminal
        CANCELLED state.

        The supported alternative to hand-editing the prod `jobs` table
        when a job is orphaned in RUNNING (e.g. a poll worker wedged on a
        no-timeout call and was restarted; nothing reclaims a stale
        RUNNING row). Also sets `cancel_requested` so a still-live worker
        can cooperatively bail. See issue #48.
        """
        try:
            record = executor.repo.get(job_id)
        except Exception:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        if record.state.status in _TERMINAL:
            raise HTTPException(
                status_code=409,
                detail=f"Job is already {record.state.status.value}; nothing to cancel",
            )

        # Signal cooperative cancellation for a live worker, then mark the
        # row terminal so an orphaned RUNNING job is reclaimed immediately.
        record.state.cancel_requested = True
        record.mark_cancelled()
        executor.repo.put(record)

        return RunSubmitResponse(job_id=str(record.spec.job_id), status=record.state.status.value)

    return router
