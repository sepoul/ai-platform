"""Schemas for the platform artifacts router.

The artifact response model itself is built dynamically at startup
(`make_artifacts_router`) — it's a discriminated union over every
artifact type contributed by the registered domains.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from ai_platform.api.schemas.workflows import ParamSpec


class ArtifactTypeSpec(BaseModel):
    """One registered artifact type — `BaseArtifact` subclass projected
    into a UI-friendly registry entry. Drives the `/artifact-types`
    viewer.
    """
    artifact_type: str           # discriminator value (e.g. "math_question")
    class_name: str              # pydantic class name (e.g. "MathQuestionArtifact")
    domain: Optional[str] = None # owning domain registered via `Domain.artifact_types`
    fields: List[ParamSpec] = [] # field metadata excluding the discriminator


class ArtifactTypeListResponse(BaseModel):
    artifact_types: List[ArtifactTypeSpec]


class ArtifactSummary(BaseModel):
    """Lightweight row for the artifact list view — enough to render
    the index and filter without hydrating every full artifact.
    """
    artifact_id: UUID
    artifact_type: str
    created_at: datetime
    created_by_job: Optional[str] = None


class ArtifactListResponse(BaseModel):
    artifacts: List[ArtifactSummary]
    total: int
