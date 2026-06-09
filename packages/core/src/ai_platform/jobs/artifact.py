"""Base artifact model.

Artifacts are the data a job produces — pure domain values, no execution
state. Each domain inherits `BaseArtifact` and adds its own fields. The
`artifact_type` field is a discriminator (subclasses override it as a
`Literal`) so a registry can hydrate raw stored payloads back into the
right concrete class.
"""
from __future__ import annotations

from datetime import datetime

from ai_platform.utilities.time import utc_now
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field




class BaseArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID = Field(default_factory=uuid4)
    artifact_type: str
    created_at: datetime = Field(default_factory=utc_now)
    created_by_job: Optional[str] = None

    # Blob-backed artifacts (PR-1). When a domain uploads user bytes via
    # `POST /media`, it stamps the returned `storage_ref` (+ content_type
    # / byte_size) here so the artifact references a blob in the storage
    # plane instead of inlining JSON. These stay `None` for the common
    # JSON-only artifact.
    storage_ref: Optional[str] = None
    content_type: Optional[str] = None
    byte_size: Optional[int] = None

    # Transient read-side hydration: `GET /artifacts/{id}` fills this in
    # with a download URL for `storage_ref`. Never persisted —
    # `ArtifactService.put` excludes it (it's a view of the ref, not
    # state).
    storage_url: Optional[str] = None
