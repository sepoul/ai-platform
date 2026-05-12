"""Math QA domain registration.

Exposes a single `register(ctx)` function that the composition root
calls during bootstrap. Builds the domain workspace, wires its
FastAPI dependency singleton, and returns a `Domain` declaring the
math QA job definition and the artifact types this domain produces.
"""
from __future__ import annotations

from ai_platform.jobs.domain import BootstrapContext, Domain
from mathai.api.dependencies import init_workspace
from mathai.math_qa.artifacts import MATH_QA_ARTIFACTS
from mathai.math_qa.workflow import build_math_qa_job_definition
from mathai.workspace.client import MathWorkspaceClient


def register(ctx: BootstrapContext) -> Domain:
    workspace_client = MathWorkspaceClient.from_artifact_service(
        artifact_service=ctx.artifact_service,
        platform_client=ctx.platform_client,
    )
    init_workspace(workspace_client)

    return Domain(
        name="math_qa",
        job_definitions=[build_math_qa_job_definition(workspace_client)],
        artifact_types=list(MATH_QA_ARTIFACTS.values()),
    )
