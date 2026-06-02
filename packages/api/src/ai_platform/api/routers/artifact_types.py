"""Platform artifact-types router — parallel to [[job_definitions]].

`POST /artifact-types` is the bundle-deploy entry point for declaring
a BaseArtifact subclass (its JSON Schema + owning domain). Idempotent
on `(name, version)`. `GET /artifact-types` returns the catalog;
`GET /artifact-types/by-name/{name}` and `/artifact-types/{id}` are
the lookup pair.

What this endpoint does NOT yet do:
- Validate the schema against existing instances of the artifact type
  (a future migration story).
- Drive (de)serialization. Today `ArtifactService` still consults its
  in-memory `registry`; the catalog row is recorded as the persistent
  shadow so wheel-install (slice 4) can register classes dynamically.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ai_platform.jobs.artifact_type_service import ArtifactTypeService
from ai_platform.runtime.registry import get_artifact_type_service
from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.structured.artifact_type_repository import (
    ArtifactTypeRecord,
)


router = APIRouter()


@router.post(
    "/artifact-types",
    response_model=ArtifactTypeRecord,
    status_code=201,
    summary="Deploy an ArtifactType (idempotent on name+version)",
)
def deploy_artifact_type(
    record: ArtifactTypeRecord,
    service: ArtifactTypeService = Depends(get_artifact_type_service),
):
    try:
        return service.deploy(record)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/artifact-types",
    response_model=list[ArtifactTypeRecord],
    summary="List deployed ArtifactTypes",
)
def list_artifact_types(
    domain: str | None = None,
    service: ArtifactTypeService = Depends(get_artifact_type_service),
):
    return service.list(domain=domain)


@router.get(
    "/artifact-types/by-name/{name}",
    response_model=ArtifactTypeRecord,
    summary="Latest-deployed version of a named ArtifactType",
)
def get_artifact_type_by_name(
    name: str,
    service: ArtifactTypeService = Depends(get_artifact_type_service),
):
    try:
        return service.get_by_name(name)
    except ObjectNotFound:
        raise HTTPException(status_code=404, detail=f"No ArtifactType named {name!r}")


@router.get(
    "/artifact-types/{type_id}",
    response_model=ArtifactTypeRecord,
    summary="Get a specific ArtifactType by id",
)
def get_artifact_type(
    type_id: str,
    service: ArtifactTypeService = Depends(get_artifact_type_service),
):
    try:
        return service.get(type_id)
    except ObjectNotFound:
        raise HTTPException(status_code=404, detail=f"ArtifactType not found: {type_id}")
