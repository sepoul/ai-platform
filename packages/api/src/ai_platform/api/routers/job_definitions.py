"""Platform job-definitions router — the bundle-deploy entry point.

`POST /job-definitions` is what a bundle deploy hits to register one
JobDefinition with the platform. Idempotent on `(name, version)` —
re-deploying overwrites payload + bumps deployed_at. The friend-test:
someone with their own domain repo runs `aiplatform.bundle.deploy_*`,
which hits this endpoint, and the row appears in the catalog.

`GET /job-definitions` returns the catalog so a deployer (or the
math-ui) can confirm what's deployed. `GET /job-definitions/{id}`
fetches one.

What this endpoint does NOT yet do:
- Validate the `code_entrypoint` resolves (would couple the API to
  having every domain importable, which is exactly what we're trying
  to avoid).
- Drive routing (`make_jobs_router` still consumes the in-memory
  `_job_controls` dict; cutover is the next PR).
- Track artifact types (separate catalog object, also next PR).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ai_platform.jobs.job_definition_service import JobDefinitionService
from ai_platform.runtime.registry import get_job_definition_service
from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.structured.job_definition_repository import (
    JobDefinitionRecord,
)


router = APIRouter()


@router.post(
    "/job-definitions",
    response_model=JobDefinitionRecord,
    status_code=201,
    summary="Deploy a JobDefinition (idempotent on name+version)",
)
def deploy_job_definition(
    record: JobDefinitionRecord,
    service: JobDefinitionService = Depends(get_job_definition_service),
):
    """Upsert a JobDefinition record into the catalog.

    The client computes the `id` as `"{name}@{version}"`; the service
    validates the join, the runtime selector, and writes. Re-POSTing
    the same `(name, version)` overwrites — that's the intended bundle-
    redeploy ergonomic.
    """
    try:
        return service.deploy(record)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/job-definitions",
    response_model=list[JobDefinitionRecord],
    summary="List deployed JobDefinitions",
)
def list_job_definitions(
    runtime_selector: str | None = None,
    service: JobDefinitionService = Depends(get_job_definition_service),
):
    return service.list(runtime_selector=runtime_selector)


@router.get(
    "/job-definitions/by-name/{name}",
    response_model=JobDefinitionRecord,
    summary="Latest-deployed version of a named JobDefinition",
)
def get_job_definition_by_name(
    name: str,
    service: JobDefinitionService = Depends(get_job_definition_service),
):
    try:
        return service.get_by_name(name)
    except ObjectNotFound:
        raise HTTPException(status_code=404, detail=f"No JobDefinition named {name!r}")


@router.get(
    "/job-definitions/{definition_id}",
    response_model=JobDefinitionRecord,
    summary="Get a specific JobDefinition by id",
)
def get_job_definition(
    definition_id: str,
    service: JobDefinitionService = Depends(get_job_definition_service),
):
    try:
        return service.get(definition_id)
    except ObjectNotFound:
        raise HTTPException(status_code=404, detail=f"JobDefinition not found: {definition_id}")
