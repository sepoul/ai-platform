"""math_conversation execution plane — `JobExecution` + `register_execution`.

Imports the pydantic_graph workflow. Only the `crewai`-runtime worker (and
the offline workflow-descriptor generator) imports this module. Heavy crew
imports stay lazy inside the node bodies, so importing this never pulls
`crewai` — that happens only when `RunCrewStep` actually runs.
"""
from __future__ import annotations

from uuid import UUID

from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.jobs.domain import BootstrapContext, ExecutionDomain
from ai_platform.jobs.execution_policy import (
    EdgeSpec,
    ExecutionPolicy,
    JobExecution,
    PersistencePolicy,
)
from ai_platform.runtime.worker_log import NullLogger, WorkerLogger
from mathai.math_conversation.artifacts import (
    MATH_CONVERSATION_ARTIFACTS,
    MathConversationArtifact,
)
from mathai.math_conversation.state import MathConversationState
from mathai.math_conversation.workflow import (
    MathConversationDeps,
    _build_artifact,
    _extract_math_conversation_result,
    math_conversation_graph,
    math_conversation_node_registry,
)
# No human gate; the conversation runs autonomously (touchpoints are submit
# + the final rendered transcript).
math_conversation_policy = ExecutionPolicy(gates=[])

MATH_CONVERSATION_EDGES = [
    EdgeSpec("SeedStep", "RunCrewStep", "Seed resolved"),
    EdgeSpec("RunCrewStep", "FinalizeStep", "Conversation done"),
    EdgeSpec("FinalizeStep", "End", "Artifact persisted"),
]


def build_math_conversation_execution(artifact_api: ArtifactService) -> JobExecution:
    def _deps_factory(payload: dict) -> MathConversationDeps:
        job_id = payload.get("_job_id")
        logger: WorkerLogger = WorkerLogger(job_id) if job_id else NullLogger()
        source_raw = payload.get("source_job_id")
        # artifact_api is required only when SeedStep hydrates from a
        # source_job_id; passing it unconditionally keeps deps stateless
        # and lets the question_text path ignore it.
        return MathConversationDeps(
            source_job_id=UUID(str(source_raw)) if source_raw else None,
            question_text=payload.get("question_text"),
            max_turns=int(payload.get("max_turns", 12)),
            logger=logger,
            artifact_api=artifact_api,
        )

    def _persist(job_id: str, state: MathConversationState) -> list[UUID]:
        """Mint the single MathConversationArtifact if not already present."""
        existing = artifact_api.get_many(state.artifact_refs) if state.artifact_refs else []
        if any(isinstance(a, MathConversationArtifact) for a in existing):
            return []
        artifact = _build_artifact(state, job_id=job_id)
        artifact_api.put(artifact)
        return [artifact.artifact_id]

    return JobExecution(
        name="math_conversation",
        graph=math_conversation_graph,
        state_type=MathConversationState,
        start_node_key="SeedStep",
        node_registry=math_conversation_node_registry,
        deps_factory=_deps_factory,
        extract_result=_extract_math_conversation_result,
        policy=math_conversation_policy,
        persistence=PersistencePolicy(on_complete=_persist),
        edges=MATH_CONVERSATION_EDGES,
    )


def register_execution(ctx: BootstrapContext) -> ExecutionDomain:
    return ExecutionDomain(
        name="math_conversation",
        job_executions=[build_math_conversation_execution(ctx.artifact_service)],
        artifact_types=list(MATH_CONVERSATION_ARTIFACTS.values()),
    )
