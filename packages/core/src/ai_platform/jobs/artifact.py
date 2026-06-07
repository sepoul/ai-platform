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
