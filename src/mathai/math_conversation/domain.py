"""math_conversation domain registration.

A sibling domain to `math_qa`: same workspace/artifact plumbing, its own
job definition and artifact type. The composition root calls `register(ctx)`
during bootstrap (see `mathapp.composition_root.DOMAINS`).
"""
from __future__ import annotations

from ai_platform.jobs.domain import BootstrapContext, Domain
from mathai.math_conversation.artifacts import MATH_CONVERSATION_ARTIFACTS
from mathai.math_conversation.workflow import build_math_conversation_job_definition
from mathai.workspace.client import MathWorkspaceClient


def register(ctx: BootstrapContext) -> Domain:
    workspace_client = MathWorkspaceClient.from_artifact_service(
        artifact_service=ctx.artifact_service,
        platform_client=ctx.platform_client,
    )

    return Domain(
        name="math_conversation",
        job_definitions=[build_math_conversation_job_definition(workspace_client)],
        artifact_types=list(MATH_CONVERSATION_ARTIFACTS.values()),
    )
