"""math_conversation pydantic_graph definition + job-definition factory.

Graph:
    SeedStep → RunCrewStep → FinalizeStep → End

`SeedStep` resolves the input into a seed question. When seeded from a
prior `math_qa` job, it hydrates that job's artifacts (question +
answer + latex + figure) into `state.seed_context` so the panel can
react to the single-shot answer rather than starting from scratch.
`RunCrewStep` runs the multi-persona CrewAI panel as a round-robin
turn loop until `conclude` is called or `max_turns` is reached,
emitting `CrewChatEvent`s for live UI. The turn-loop shape (one
single-task Crew per turn, owned by Python) is the design choice that
lets us early-exit on conclude; see `crew/crew.py`. `FinalizeStep`
assembles and persists the single `MathConversationArtifact`.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.runtime.worker_log import NullLogger, WorkerLogger
from mathai.math_conversation.artifacts import (
    ConversationTurn,
    MathConversationArtifact,
)
from mathai.math_conversation.crew.callbacks import CrewChatEmitter
from mathai.math_conversation.crew.crew import (
    append_to_transcript,
    build_panel,
    build_turn_crew,
)
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
    `artifact_api` is the platform-shared service used by `SeedStep` to
    hydrate a source math_qa job's artifacts; it is required only for
    the `source_job_id` path and may be `None` for question_text-only
    runs and unit tests.
    """
    source_job_id: Optional[UUID] = None
    question_text: Optional[str] = None
    max_turns: int = 12
    logger: WorkerLogger = field(default_factory=NullLogger)
    artifact_api: Optional[ArtifactService] = None


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
            return RunCrewStep()

        # source_job_id path — hydrate the prior math_qa job's artifacts.
        # MathConversationInput's `exactly_one_source` validator means this
        # branch implies source_job_id is set; assert for clarity.
        assert ctx.deps.source_job_id is not None, "Input validator must guarantee one source"
        if ctx.deps.artifact_api is None:
            raise RuntimeError(
                "artifact_api is required to hydrate from source_job_id; "
                "the worker bootstrap should wire it into MathConversationDeps."
            )

        ctx.state.source_job_id = ctx.deps.source_job_id
        await log.info(f"hydrating from source math_qa job {ctx.deps.source_job_id}")

        source_artifacts = _load_source_artifacts(ctx.deps.artifact_api, ctx.deps.source_job_id)
        question = source_artifacts.get("math_question")
        if question is None:
            raise RuntimeError(
                f"Source job {ctx.deps.source_job_id} has no math_question artifact; "
                "can't seed a conversation without the original question."
            )

        ctx.state.seed_question = question.question_text
        ctx.state.seed_context = _project_seed_context(source_artifacts)
        present = sorted(k for k, v in ctx.state.seed_context.items() if v is not None)
        await log.info(f"hydrated source job: question + {present}")
        return RunCrewStep()


def _load_source_artifacts(
    artifact_api: ArtifactService, source_job_id: UUID
) -> dict[str, Any]:
    """Return `{artifact_type: BaseArtifact}` for every artifact the
    source math_qa job produced.

    Uses `artifact_api.list_by_job` which pushes the filter into
    storage — single SQL query on Supabase (was: scan-all-ids +
    one-get-per-id, an N+1 over the whole artifacts table). The single
    `math_qa` job seeding a conversation produces ≤5 artifacts
    (question, answer, latex, figure, optional comment), so iterating
    the result for the first-of-type collapse is constant-time.
    """
    try:
        artifacts = artifact_api.list_by_job(source_job_id)
    except Exception:
        artifacts = []
    by_type: dict[str, Any] = {}
    for artifact in artifacts:
        # First wins — defensive against duplicate types on one job.
        by_type.setdefault(artifact.artifact_type, artifact)
    return by_type


def _project_seed_context(source_artifacts: dict[str, Any]) -> dict[str, Any]:
    """Project the math_qa artifact bundle into the panel's seed context.

    Only the fields the panel actually conditions on are projected. The
    artifact-type names mirror `mathai.math_qa.artifacts` discriminators.
    """
    answer = source_artifacts.get("ai_answer")
    latex = source_artifacts.get("latex_answer")
    figure = source_artifacts.get("figure")
    question = source_artifacts.get("math_question")
    return {
        "answer": answer.answer_text if answer is not None else None,
        "latex": latex.latex_source if latex is not None else None,
        "figure": figure.spec if figure is not None else None,
        "topic": question.topic if question is not None else None,
        "difficulty": question.difficulty if question is not None else None,
    }


@dataclass
class RunCrewStep(BaseNode[MathConversationState, MathConversationDeps]):
    stage_label = "Brainstorm"
    stage_description = "Run the CrewAI panel until max_turns or conclude()"

    async def run(
        self, ctx: GraphRunContext[MathConversationState, MathConversationDeps]
    ) -> "FinalizeStep":
        log = ctx.deps.logger.for_stage("RunCrewStep")

        # Defensive: a resumed checkpoint may already carry concluded=True
        # (a prior run flipped it via the conclude tool). Skip the loop —
        # FinalizeStep will persist whatever turns are on state.
        if ctx.state.concluded:
            await log.info("entered with state.concluded=True; skipping panel loop")
            ctx.state.stop_reason = "concluded"
            return FinalizeStep()

        panel = build_panel()
        emitter = CrewChatEmitter(ctx.deps.logger, turns_budget=ctx.state.max_turns)

        # Roll call — UI shows each panelist joining before the first turn.
        for name in panel.order:
            await emitter.emit_signed_in(panel.role_by_name[name], panel.display_by_name[name])

        seed_question = ctx.state.seed_question or ""
        transcript = ""
        max_turns = ctx.state.max_turns
        await log.info(f"panel ready: {len(panel.order)} personae, max_turns={max_turns}")

        for turn_idx in range(max_turns):
            persona_name = panel.order[turn_idx % len(panel.order)]
            role = panel.role_by_name[persona_name]
            display = panel.display_by_name[persona_name]

            await emitter.emit_typing(role, display)
            crew = build_turn_crew(
                panel,
                persona_name,
                transcript,
                seed_question,
                seed_context=ctx.state.seed_context,
            )
            result = await asyncio.to_thread(crew.kickoff)

            content = str(getattr(result, "raw", result)).strip()
            cost = float(getattr(getattr(result, "token_usage", None), "total_cost", 0.0) or 0.0)

            ctx.state.turns.append(
                ConversationTurn(
                    turn_index=turn_idx,
                    agent_role=role,
                    agent_persona=persona_name,
                    content=content,
                    cost_usd=cost,
                )
            )
            ctx.state.cost_so_far += cost
            transcript = append_to_transcript(transcript, role, content)

            await emitter.emit_message(role, display, turn_idx, content, cost_usd=cost)
            await emitter.emit_status(turns_used=turn_idx + 1, cost_usd=ctx.state.cost_so_far)

            # Mirror the closure-captured signal into state so the
            # checkpoint preserves the reason for resume / debugging.
            if panel.conclude_signal.fired:
                ctx.state.concluded = True
                await emitter.emit_concluded(role, display, content=panel.conclude_signal.reason)
                await log.info(
                    f"panel concluded at turn {turn_idx}: {panel.conclude_signal.reason!r}"
                )
                break
        else:
            await log.info(f"panel reached max_turns={max_turns} without concluding")

        # Roll out — UI shows the panel dispersing.
        for name in panel.order:
            await emitter.emit_signed_out(panel.role_by_name[name], panel.display_by_name[name])

        ctx.state.stop_reason = "concluded" if ctx.state.concluded else "max_turns"
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
