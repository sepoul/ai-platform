"""Demo artifacts — a single typed output for the echo job."""
from __future__ import annotations

from typing import Literal

from ai_platform.jobs.artifact import BaseArtifact


class DemoEchoArtifact(BaseArtifact):
    """The single artifact the demo job produces — the input message
    uppercased. Just enough to exercise the artifact persistence /
    catalog round-trip without dragging in a real domain.
    """

    artifact_type: Literal["demo_echo"] = "demo_echo"
    original: str
    echoed: str


DEMO_ARTIFACTS: dict[str, type[BaseArtifact]] = {
    "demo_echo": DemoEchoArtifact,
}
