"""Platform job-run endpoints — generic dispatch by job_type.

Built as a factory so the submit body reflects the discriminated union of
every registered `JobDefinition.submit_input_type`. The TS client narrows
on `job_type` for both the request and the response.
"""
# NOTE: deliberately no `from __future__ import annotations` — FastAPI
# needs to resolve the dynamically-built `RunSubmitRequest` body annotation
# at runtime, which requires real (non-stringified) annotations.

from fastapi import APIRouter, Depends, HTTPException
from pydantic import RootModel

from ai_platform.runtime.registry import get_compute, get_executor, get_job_definitions
from ai_platform.api.schemas.jobs import (
    RunSubmitResponse,
    build_review_request_model,
    build_run_submit_request_model,
)
from ai_platform.compute.base import ComputeBackend
from ai_platform.jobs.execution_policy import JobDefinition
from ai_platform.jobs.graph_execution import GraphCheckpoint, GraphJobExecutor
from ai_platform.workspace.storage.structured.job_repository import JobStatus


def make_job_runs_router(jobs: dict[str, JobDefinition]) -> APIRouter:
    router = APIRouter()

    RunSubmitRequest = build_run_submit_request_model(
        [j.submit_input_type for j in jobs.values()]
    )
    ReviewRequest = build_review_request_model(
        [g.review_type for j in jobs.values() for g in j.policy.gates]
    )

    @router.post("/jobs/runs/submit", response_model=RunSubmitResponse)
    def submit_job_run(
        body: RunSubmitRequest,
        executor: GraphJobExecutor = Depends(get_executor),
        jobs_dep: dict[str, JobDefinition] = Depends(get_job_definitions),
        compute: ComputeBackend = Depends(get_compute),
    ):
        inner = body.root if isinstance(body, RootModel) else body
        params = inner.model_dump(exclude={"job_type"})
        job_def = jobs_dep[inner.job_type]

        record = executor.submit_graph_job(
            job_type=job_def.name,
            graph_ref=job_def.graph_ref,
            initial_state={},
            deps_payload=params,
            created_by=params.get("created_by"),
        )
        compute.enqueue(str(record.spec.job_id))
        return RunSubmitResponse(job_id=str(record.spec.job_id), status=record.state.status.value)

    @router.post("/jobs/{job_id}/review", response_model=RunSubmitResponse)
    def review_job(
        job_id: str,
        body: ReviewRequest,
        executor: GraphJobExecutor = Depends(get_executor),
        jobs_dep: dict[str, JobDefinition] = Depends(get_job_definitions),
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

        gate = job_def.policy.gate_for(gated_node)
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

        state = job_def.state_type.model_validate(checkpoint.state_data)
        state.set_review(gated_node, review)

        updated_ckpt = GraphCheckpoint(
            state_data=state.model_dump(),
            next_node_key=checkpoint.next_node_key,
            gated_node=None,
            attempt=checkpoint.attempt,
        )
        record.state.resume_token = updated_ckpt.model_dump_json()
        record.state.status = JobStatus.PENDING
        record.state.waiting_for = None
        record._bump()
        executor.repo.put(record)

        # Resuming is a "submit moment" too — queue-based backends
        # need to re-deliver this job_id to a worker.
        compute.enqueue(str(record.spec.job_id))

        return RunSubmitResponse(job_id=str(record.spec.job_id), status=record.state.status.value)

    return router
