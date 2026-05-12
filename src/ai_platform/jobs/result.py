"""Typed job results.

Each domain registers a concrete subclass of `BaseJobResult` on its
`JobDefinition`. The platform jobs router exposes the union of all
registered result types as a Pydantic discriminated union keyed on
`job_type`, so a TypeScript client can narrow on `job_type` to get the
right shape.
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BaseJobResult(BaseModel):
    """Base class for typed job results.

    Subclasses MUST declare a `job_type: Literal["<name>"] = "<name>"`
    field whose value matches the `JobDefinition.name`. That field is
    the discriminator across the API's result union.

    `artifact_refs` is the list of artifact IDs the job produced. Clients
    can resolve each ID via the workspace `/artifacts/{id}` endpoint,
    or rely on domain-specific typed fields the result also exposes.
    """

    model_config = ConfigDict(extra="forbid")

    artifact_refs: list[UUID] = Field(default_factory=list)
