"""math_conversation pydantic_graph definition + job-definition factory.

Graph:
    SeedStep → RunCrewStep → FinalizeStep → End

`SeedStep` resolves the input into a seed question (and, when seeding
from a `math_qa` job, projects that job's artifacts into
`state.seed_context`). `RunCrewStep` runs the CrewAI panel and
accumulates turns. `FinalizeStep` assembles the single
`MathConversationArtifact` and persists it.

v1 status: the node *bodies* for the crew run and seed hydration land in
later tickets (T5/T6). This module establishes the graph topology, the
`JobDefinition`, and end-of-run persistence so the domain registers and
runs to End — the crew internals slot into `RunCrewStep` without
changing this skeleton.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from ai_platform.runtime.worker_log import NullLogger, WorkerLogger
from mathai.math_conversation.artifacts import MathConversationArtifact
from mathai.math_conversation.models import MathConversationResult
from mathai.math_conversation.state import MathConversationState

# NOTE: this module is the execution engine (graph + nodes + extraction).
# The JobControl/JobExecution builders + ExecutionPolicy/edges live in
# control.py / execution.py so the API never imports the engine.


# ---------------------------------------------------------------------------
# Deps — per-run inputs; no domain client (nodes are pure computation)
# ---------------------------------------------------------------------------

@dataclass
class MathConversationDeps:
    """Per-run inputs for the math_conversation graph.

    Exactly one of `source_job_id` / `question_text` is set (enforced by
    `MathConversationInput`). `logger` is bound to this job_id by the
    deps_factory; it defaults to `NullLogger` outside the runner (tests).
    """
    source_job_id: Optional[UUID] = None
    question_text: Optional[str] = None
    max_turns: int = 12
    logger: WorkerLogger = field(default_factory=NullLogger)


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

@dataclass
class SeedStep(BaseNode[MathConversationState, MathConversationDeps]):
    stage_label = "Seed"
    stage_description = "Resolve the input into a seed question + context"

    async def run(
        self, ctx: GraphRunContext[MathConversationState, MathConversationDeps]
    ) -> "RunCrewStep":
        log = ctx.deps.logger.for_stage("SeedStep")
        ctx.state.max_turns = ctx.deps.max_turns
        if ctx.deps.question_text:
            ctx.state.seed_question = ctx.deps.question_text
            await log.info(f"seeded from fresh question ({len(ctx.deps.question_text)} chars)")
        else:
            # Seeding from a prior math_qa job — artifact hydration lands
            # in T6. For now record provenance so the graph runs to End.
            ctx.state.source_job_id = ctx.deps.source_job_id
            await log.info(f"seeding from source job {ctx.deps.source_job_id} (hydration: T6)")
        return RunCrewStep()


@dataclass
class RunCrewStep(BaseNode[MathConversationState, MathConversationDeps]):
    stage_label = "Brainstorm"
    stage_description = "Run the CrewAI panel until max_turns or conclude()"

    async def run(
        self, ctx: GraphRunContext[MathConversationState, MathConversationDeps]
    ) -> "FinalizeStep":
        log = ctx.deps.logger.for_stage("RunCrewStep")
        # Crew assembly + the turn loop land in T5/T6. The skeleton
        # records the default stop reason and leaves an empty transcript.
        ctx.state.stop_reason = "concluded" if ctx.state.concluded else "max_turns"
        await log.info(f"crew run stub — {len(ctx.state.turns)} turn(s), stop_reason={ctx.state.stop_reason}")
        return FinalizeStep()


@dataclass
class FinalizeStep(BaseNode[MathConversationState, MathConversationDeps]):
    stage_label = "Finalize"
    stage_description = "Assemble and persist the MathConversationArtifact"

    async def run(
        self, ctx: GraphRunContext[MathConversationState, MathConversationDeps]
    ) -> End[None]:
        log = ctx.deps.logger.for_stage("FinalizeStep")
        await log.info(
            f"finalizing: {len(ctx.state.turns)} turn(s), "
            f"total_cost=${ctx.state.cost_so_far:.4f}, stop_reason={ctx.state.stop_reason}"
        )
        return End(None)


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

math_conversation_graph = Graph(
    nodes=(SeedStep, RunCrewStep, FinalizeStep),
    state_type=MathConversationState,
)

math_conversation_node_registry: dict[str, type] = {
    "SeedStep": SeedStep,
    "RunCrewStep": RunCrewStep,
    "FinalizeStep": FinalizeStep,
}


# ---------------------------------------------------------------------------
# Result extraction
# ---------------------------------------------------------------------------

def _build_artifact(state: MathConversationState, job_id: Optional[str] = None) -> MathConversationArtifact:
    return MathConversationArtifact(
        created_by_job=job_id,
        source_job_id=state.source_job_id,
        seed_question=state.seed_question or "",
        turns=list(state.turns),
        total_cost_usd=state.cost_so_far,
        stop_reason=state.stop_reason or "max_turns",
    )


def _extract_math_conversation_result(state: MathConversationState) -> MathConversationResult:
    """Cheap in-state preview stored on `record.state.result_payload`.

    The canonical result is rebuilt by `_fetch_result` from the workspace.
    """
    return MathConversationResult(
        conversation=_build_artifact(state),
        artifact_refs=list(state.artifact_refs),
    )
