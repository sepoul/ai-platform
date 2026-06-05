"""math_conversation control plane — `JobControl` (schemas) + `register_control`.

Engine-free: imports models/artifacts only, never the pydantic_graph
workflow or the crew engine. The API imports this. The execution plane
(graph + crew) lives in `execution.py`.
"""
from __future__ import annotations

from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.jobs.domain import BootstrapContext, ControlDomain
from ai_platform.jobs.execution_policy import JobControl
from ai_platform.jobs.result_fetcher import hydrate_artifact_refs
from mathai.math_conversation.api import make_math_conversation_router
from mathai.math_conversation.artifacts import (
    MATH_CONVERSATION_ARTIFACTS,
    MathConversationArtifact,
)
from mathai.math_conversation.models import (
    MathConversationInput,
    MathConversationResult,
)


def build_math_conversation_control(artifact_api: ArtifactService) -> JobControl:
    def _fetch_result(record) -> MathConversationResult:
        artifacts = hydrate_artifact_refs(record, artifact_api)
        conversation = next(
            (a for a in artifacts if isinstance(a, MathConversationArtifact)), None
        )
        return MathConversationResult(
            conversation=conversation,
            artifact_refs=[a.artifact_id for a in artifacts],
        )

    return JobControl(
        name="math_conversation",
        label="math_conversation_graph",
        submit_input_type=MathConversationInput,
        result_type=MathConversationResult,
        gates=[],  # no human gate; the conversation runs autonomously
        fetch_result=_fetch_result,
    )


def register_control(ctx: BootstrapContext) -> ControlDomain:
    return ControlDomain(
        name="math_conversation",
        job_controls=[build_math_conversation_control(ctx.artifact_service)],
        # Schema-export router: surfaces CrewChatEvent into OpenAPI so the
        # math-ui chat parser can derive the type from `gen:api` instead
        # of hand-authoring it. Not for live consumption — live events
        # ride the existing `/jobs/{id}/logs/stream` SSE.
        routers=[make_math_conversation_router()],
        artifact_types=list(MATH_CONVERSATION_ARTIFACTS.values()),
        runtime_selector="crewai",
        code_entrypoint="mathai.math_conversation.execution:register_execution",
        control_entrypoint="mathai.math_conversation.control:register_control",
    )
