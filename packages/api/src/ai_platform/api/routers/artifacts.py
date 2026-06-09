"""Platform artifacts router — typed read access to the workspace
artifact store, plus a registry view of every artifact type a domain
has declared.

The response model for `GET /artifacts/{id}` is a discriminated union
built at startup from every registered domain's artifact types. This
keeps the router platform-level (no domain imports) while still giving
the OpenAPI schema typed variants per `artifact_type`.
"""
from __future__ import annotations

from typing import Annotated, Optional, Union
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field

from ai_platform.jobs.pydantic_fields import params_from_model
from ai_platform.api.schemas.artifacts import (
    ArtifactListResponse,
    ArtifactSummary,
    ArtifactTypeListResponse,
    ArtifactTypeSpec,
)
from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.runtime.registry import get_artifact_service
from ai_platform.workspace.storage.exceptions import ObjectNotFound


def _spec_for(
    artifact_cls: type[BaseArtifact],
    owners: dict[str, str],
) -> ArtifactTypeSpec:
    artifact_type = artifact_cls.model_fields["artifact_type"].default
    return ArtifactTypeSpec(
        artifact_type=str(artifact_type) if artifact_type is not None else artifact_cls.__name__,
        class_name=artifact_cls.__name__,
        domain=owners.get(artifact_type) if artifact_type is not None else None,
        fields=params_from_model(artifact_cls, skip_fields=("artifact_type",)),
    )


def make_artifacts_router(
    artifact_types: list[type[BaseArtifact]],
    artifact_owners: Optional[dict[str, str]] = None,
) -> APIRouter:
    """Build the router with a response model that's a discriminated
    union over the supplied artifact types. Mounted by `build_api`
    after `register_control_domains` has aggregated every domain's types.
    """
    owners = dict(artifact_owners or {})
    router = APIRouter(prefix="/artifacts", tags=["Platform / Artifacts"])

    if artifact_types:
        # Annotated[Union[...], Field(discriminator="artifact_type")]
        # gives FastAPI the typed branches it needs to render in
        # `oneOf` form on the OpenAPI schema.
        ArtifactResponse = Annotated[
            Union[tuple(artifact_types)],  # type: ignore[valid-type]
            Field(discriminator="artifact_type"),
        ]
    else:
        # No domain registered any artifact types yet — fall back to
        # the open base. The endpoint still works; the schema is just
        # less informative.
        ArtifactResponse = BaseArtifact  # type: ignore[assignment]

    # Declared before `/{artifact_id}` so the path matches before the
    # UUID converter rejects "types" as 422.
    @router.get("/types", response_model=ArtifactTypeListResponse)
    def list_artifact_types():
        return ArtifactTypeListResponse(
            artifact_types=[_spec_for(cls, owners) for cls in artifact_types]
        )

    @router.get("", response_model=ArtifactListResponse)
    def list_artifacts(
        job_id: Optional[str] = Query(default=None, description="Filter by `created_by_job`."),
        artifact_type: Optional[str] = Query(default=None, description="Filter by discriminator."),
        limit: int = Query(default=100, ge=1, le=500),
        service: ArtifactService = Depends(get_artifact_service),
    ):
        # Push the filter into the repo so Supabase resolves the whole
        # listing in one round-trip (used to be: list_ids() + get(id)
        # per row — 1 query per artifact). `job_id` wins over
        # `artifact_type` when both are provided; if both are needed,
        # the secondary filter happens client-side (rare combo).
        try:
            if job_id is not None:
                artifacts = service.list_by_job(job_id, limit=limit)
                if artifact_type is not None:
                    artifacts = [a for a in artifacts if a.artifact_type == artifact_type]
            elif artifact_type is not None:
                artifacts = service.list_by_type(artifact_type, limit=limit)
            else:
                artifacts = service.list_all(limit=limit)
        except ObjectNotFound:
            artifacts = []

        rows = [
            ArtifactSummary(
                artifact_id=artifact.artifact_id,
                artifact_type=artifact.artifact_type,
                created_at=artifact.created_at,
                created_by_job=artifact.created_by_job,
            )
            for artifact in artifacts
        ]
        return ArtifactListResponse(artifacts=rows, total=len(rows))

    @router.get("/{artifact_id}", response_model=ArtifactResponse)
    def get_artifact(
        artifact_id: UUID,
        service: ArtifactService = Depends(get_artifact_service),
    ):
        try:
            artifact = service.get(artifact_id)
        except ObjectNotFound:
            raise HTTPException(
                status_code=404, detail=f"Artifact '{artifact_id}' not found"
            )
        # Hydrate a blob-backed artifact's ref into a download URL the
        # client can fetch (PR-1). The ref carries `/` separators, so
        # encode it whole as the query value.
        if getattr(artifact, "storage_ref", None):
            artifact.storage_url = f"/media/download?ref={quote(artifact.storage_ref, safe='')}"
        return artifact

    return router
