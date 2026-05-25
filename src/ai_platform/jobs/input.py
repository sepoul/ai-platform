"""Typed job submit inputs.

Each domain that wants typed submit validation registers a concrete subclass
of `BaseJobInput` on its `JobControl.submit_input_type`. The platform
job-runs router exposes the union of all registered input types as a
Pydantic discriminated union keyed on `job_type`, so a TypeScript client can
narrow on `job_type` to get the right request shape.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaseJobInput(BaseModel):
    """Base class for typed submit inputs.

    Subclasses MUST declare a `job_type: Literal["<name>"] = "<name>"` field
    whose value matches the `JobControl.name`. That field is the
    discriminator across the API's request union.
    """

    model_config = ConfigDict(extra="forbid")
