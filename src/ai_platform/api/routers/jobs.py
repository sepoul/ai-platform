"""Platform jobs router — generic job status / list / result endpoints.

Built as a factory so that the response models reflect the discriminated
union of every registered `JobDefinition.result_type`. This is what the
TypeScript client narrows on (`job_type` is the discriminator).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ai_platform.runtime.registry import get_executor, get_job_definitions
from ai_platform.api.schemas.jobs import (
    JobListParams,
    build_job_result_response_model,
    build_job_status_response_model,
)
from ai_platform.jobs.execution_policy import JobDefinition
from ai_platform.jobs.graph_execution import GraphJobExecutor
from ai_platform.workspace.storage.structured.job_repository import JobStatus


def make_jobs_router(jobs: dict[str, JobDefinition]) -> APIRouter:
    router = APIRouter()

    result_types = [j.result_type for j in jobs.values()]
    JobStatusResponse = build_job_status_response_model(result_types)
    JobResultResponse = build_job_result_response_model(result_types)

    def _typed_result(record, jobs_dep: dict[str, JobDefinition]):
        if record.state.result_payload is None:
            return None
        job_def = jobs_dep.get(record.spec.job_type)
        if job_def is None:
            return None
        return job_def.result_type.model_validate(record.state.result_payload)

    def _to_status(record, jobs_dep: dict[str, JobDefinition]):
        return JobStatusResponse(
            job_id=str(record.spec.job_id),
            job_type=record.spec.job_type,
            status=record.state.status.value,
            created_at=record.created_at,
            stage=record.state.stage,
            percent=record.state.percent,
            message=record.state.message,
            waiting_for=record.state.waiting_for,
            error_message=record.state.error_message,
            result=_typed_result(record, jobs_dep),
        )

    @router.get("/jobs/{job_id}", response_model=JobStatusResponse)
    def get_job_status(
        job_id: str,
        executor: GraphJobExecutor = Depends(get_executor),
        jobs_dep: dict[str, JobDefinition] = Depends(get_job_definitions),
    ):
        try:
            record = executor.repo.get(job_id)
        except Exception:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return _to_status(record, jobs_dep)

    @router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
    def get_job_result(
        job_id: str,
        executor: GraphJobExecutor = Depends(get_executor),
        jobs_dep: dict[str, JobDefinition] = Depends(get_job_definitions),
    ):
        try:
            record = executor.repo.get(job_id)
        except Exception:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        if record.state.status not in (JobStatus.SUCCEEDED, JobStatus.WAITING_INPUT):
            raise HTTPException(
                status_code=409,
                detail=f"Job is {record.state.status.value}, not SUCCEEDED or WAITING_INPUT",
            )

        job_def = jobs_dep.get(record.spec.job_type)
        if job_def is None:
            raise HTTPException(
                status_code=500,
                detail=f"Job type '{record.spec.job_type}' has no registered definition",
            )

        # Prefer the workspace-backed canonical artifact when the domain
        # provides a fetcher; fall back to the in-record payload preview.
        if job_def.fetch_result is not None:
            try:
                result = job_def.fetch_result(record)
            except Exception as e:
                raise HTTPException(
                    status_code=404,
                    detail=f"Result artifact for job {job_id} not found: {e}",
                )
        else:
            result = _typed_result(record, jobs_dep)

        return JobResultResponse(job_id=job_id, result=result)

    @router.get("/jobs", response_model=list[JobStatusResponse])
    def list_jobs(
        params: Annotated[JobListParams, Query()],
        executor: GraphJobExecutor = Depends(get_executor),
        jobs_dep: dict[str, JobDefinition] = Depends(get_job_definitions),
    ):
        status_filter = None
        if params.status:
            try:
                status_filter = JobStatus(params.status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {params.status}")

        records = executor.repo.list(status=status_filter, job_type=params.job_type)

        if params.created_after:
            records = [r for r in records if r.created_at.date() >= params.created_after]
        if params.created_before:
            records = [r for r in records if r.created_at.date() <= params.created_before]

        records = records[params.offset : params.offset + params.limit]
        return [_to_status(r, jobs_dep) for r in records]

    return router
