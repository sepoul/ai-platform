"""Platform artifacts router — typed read access to the workspace
artifact store, plus a registry view of every artifact type a domain
has declared.

The response model for `GET /artifacts/{id}` is a discriminated union
built at startup from every registered domain's artifact types. This
keeps the router platform-level (no domain imports) while still giving
the OpenAPI schema typed variants per `artifact_type`.
"""
from __future__ import annotations

from typing import Annotated, List, Optional, Union
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field, create_model

from ai_platform.jobs.pydantic_fields import params_from_model
from ai_platform.api.schemas.artifacts import (
    ArtifactListResponse,
    ArtifactSummary,
    ArtifactTypeListResponse,
    ArtifactTypeSpec,
    BatchArtifactRequest,
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

    # Full-projection page: the same discriminated union as
    # `GET /artifacts/{id}`, returned inline by `GET /artifacts?full=true`
    # so one request hydrates a whole gallery (PR-3a). The default stays
    # the cheap `ArtifactSummary` page.
    FullArtifactListResponse = create_model(
        "FullArtifactListResponse",
        artifacts=(List[ArtifactResponse], ...),  # type: ignore[valid-type]
        total=(int, ...),
    )

    # Query-string keys the list endpoint owns. Anything else is treated
    # as an equality filter on a domain field (PR-3b).
    _RESERVED_QS = {"job_id", "artifact_type", "limit", "offset", "full"}

    def _hydrate_url(artifact: BaseArtifact) -> BaseArtifact:
        # Blob-backed artifact → fill `storage_url` with a fetchable
        # download path (PR-1). The ref carries `/`, so encode it whole.
        if getattr(artifact, "storage_ref", None):
            artifact.storage_url = (
                f"/media/download?ref={quote(artifact.storage_ref, safe='')}"
            )
        return artifact

    # Declared before `/{artifact_id}` so the path matches before the
    # UUID converter rejects "types" as 422.
    @router.get("/types", response_model=ArtifactTypeListResponse)
    def list_artifact_types():
        return ArtifactTypeListResponse(
            artifact_types=[_spec_for(cls, owners) for cls in artifact_types]
        )

    @router.get("", response_model=Union[FullArtifactListResponse, ArtifactListResponse])
    def list_artifacts(
        request: Request,
        job_id: Optional[str] = Query(default=None, description="Filter by `created_by_job`."),
        artifact_type: Optional[str] = Query(default=None, description="Filter by discriminator."),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0, description="Rows to skip (pagination)."),
        full: bool = Query(
            default=False,
            description="Return full typed artifacts inline instead of summaries.",
        ),
        service: ArtifactService = Depends(get_artifact_service),
    ):
        # Envelope filters + any extra query-string keys (equality filters
        # on whitelisted domain fields, e.g. `&source_note_id=<id>`) +
        # limit/offset all compile to one backend query (PR-3b/3c), so
        # latency is O(page) instead of scan-then-filter.
        fields = {
            k: v for k, v in request.query_params.items() if k not in _RESERVED_QS
        }
        try:
            artifacts = service.query(
                artifact_type=artifact_type,
                job_id=job_id,
                fields=fields or None,
                limit=limit,
                offset=offset,
            )
        except ValueError as e:
            # Unknown / non-whitelisted filter field.
            raise HTTPException(status_code=400, detail=str(e))
        except ObjectNotFound:
            artifacts = []

        if full:
            rows_full = [_hydrate_url(a) for a in artifacts]
            return FullArtifactListResponse(artifacts=rows_full, total=len(rows_full))

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

    @router.post("/batch", response_model=List[ArtifactResponse])
    def batch_get_artifacts(
        body: BatchArtifactRequest,
        service: ArtifactService = Depends(get_artifact_service),
    ):
        """Hydrate many artifacts in one round-trip (PR-3d) — kills the
        per-id `GET /artifacts/{id}` fan-out when reading
        `result.artifact_refs` or a SeedStep set. Fail-loud: any missing
        id 404s the whole batch (matches `ArtifactService.get_many`)."""
        try:
            artifacts = service.get_many(body.ids)
        except ObjectNotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        return [_hydrate_url(a) for a in artifacts]

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
        return _hydrate_url(artifact)

    return router
