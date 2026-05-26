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
        try:
            ids = service.repo.list_ids()
        except ObjectNotFound:
            ids = []

        rows: list[ArtifactSummary] = []
        for raw_id in ids:
            try:
                artifact = service.get(raw_id)
            except (ObjectNotFound, ValueError):
                # Skip rows we can't hydrate (unknown artifact_type, etc.)
                # — keeps the index resilient when a domain is removed.
                continue
            if job_id is not None and artifact.created_by_job != job_id:
                continue
            if artifact_type is not None and artifact.artifact_type != artifact_type:
                continue
            rows.append(
                ArtifactSummary(
                    artifact_id=artifact.artifact_id,
                    artifact_type=artifact.artifact_type,
                    created_at=artifact.created_at,
                    created_by_job=artifact.created_by_job,
                )
            )
            if len(rows) >= limit:
                break

        return ArtifactListResponse(artifacts=rows, total=len(rows))

    @router.get("/{artifact_id}", response_model=ArtifactResponse)
    def get_artifact(
        artifact_id: UUID,
        service: ArtifactService = Depends(get_artifact_service),
    ):
        try:
            return service.get(artifact_id)
        except ObjectNotFound:
            raise HTTPException(
                status_code=404, detail=f"Artifact '{artifact_id}' not found"
            )

    return router
