"""Demo domain models — input + result for the trivial echo job."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.result import BaseJobResult


class DemoInput(BaseJobInput):
    """Submit input for the demo job."""
    model_config = ConfigDict(extra="forbid")

    job_type: Literal["demo"] = "demo"
    message: str = Field(..., description="Any text. The demo job echoes it back uppercased.")
    created_by: Optional[str] = Field(None, description="Submitting user.")


class DemoResult(BaseJobResult):
    """Result payload for the demo job."""
    model_config = ConfigDict(extra="forbid")

    job_type: Literal["demo"] = "demo"
    echo: Optional["DemoEchoArtifact"] = None
    artifact_refs: list[str] = Field(default_factory=list)


# Forward-ref imports — kept here to avoid circular at the artifact layer.
from aiplatform_demo.artifacts import DemoEchoArtifact  # noqa: E402

DemoResult.model_rebuild()
