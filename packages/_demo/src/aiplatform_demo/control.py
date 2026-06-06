"""Demo domain control plane.

Engine-free: imports only models + artifacts. The API process imports
this at boot to register the JobControl + ArtifactType rows.
"""
from __future__ import annotations

from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.jobs.domain import BootstrapContext, ControlDomain
from ai_platform.jobs.execution_policy import JobControl
from ai_platform.jobs.result_fetcher import hydrate_artifact_refs
from aiplatform_demo.artifacts import DEMO_ARTIFACTS, DemoEchoArtifact
from aiplatform_demo.models import DemoInput, DemoResult


def build_demo_control(artifact_api: ArtifactService) -> JobControl:
    def _fetch_result(record) -> DemoResult:
        artifacts = hydrate_artifact_refs(record, artifact_api)
        echo = next((a for a in artifacts if isinstance(a, DemoEchoArtifact)), None)
        return DemoResult(
            echo=echo,
            artifact_refs=[a.artifact_id for a in artifacts],
        )

    return JobControl(
        name="demo",
        label="demo_echo",
        submit_input_type=DemoInput,
        result_type=DemoResult,
        gates=[],  # no human review
        fetch_result=_fetch_result,
    )


def register_control(ctx: BootstrapContext) -> ControlDomain:
    return ControlDomain(
        name="demo",
        job_controls=[build_demo_control(ctx.artifact_service)],
        artifact_types=list(DEMO_ARTIFACTS.values()),
        runtime_selector="default",
        code_entrypoint="aiplatform_demo.execution:register_execution",
        control_entrypoint="aiplatform_demo.control:register_control",
    )
