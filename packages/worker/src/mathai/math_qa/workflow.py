"""
Math Q&A pydantic_graph definition + job definition factory.

Graph:
    ReceiveQuestionStep
      → GenerateAnswerStep
        → DecideFigureStep
            ├─ (yes) RenderFigureStep → GenerateLatexStep → End
            └─ (no)  GenerateLatexStep → End

`DecideFigureStep` is control logic — a fast Haiku call that
classifies whether the answer would benefit from a textbook-style
figure. No registry prompt; the message is one sentence and the
output is a single boolean.

`RenderFigureStep` (when triggered) converges on a structurally
valid figure spec via the `validate_figure` tool loop and emits a
`FigureArtifact`.

`GenerateLatexStep` converts the AI's plain-text answer into
KaTeX-validated LaTeX via `validate_latex` and emits a
`LatexAnswerArtifact`.

The human review step is NOT a graph node — it's declared in
`math_qa_policy` and fires after `GenerateLatexStep` so the user
reviews text + figure (when present) + LaTeX together.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from pydantic_ai import Tool
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from mathai.math_qa.artifacts import (
    FigureArtifact,
    GeneratedAnswerArtifact,
    LatexAnswerArtifact,
    MathQuestionArtifact,
    UserCommentArtifact,
)
from mathai.math_qa.models import (
    FigureDecision,
    FigureOutput,
    GeneratedAnswer,
    LatexAnswer,
    MathQAInput,
    MathQAResult,
    MathQuestion,
    UserComment,
)
from mathai.math_qa.state import MathQAState
from mathai.math_qa.tools import validate_figure, validate_latex
from ai_platform.ai.providers.basic_agent import basic_agent
from ai_platform.runtime.worker_log import NullLogger, WorkerLogger

# NOTE: this module is the execution engine (graph + nodes + extraction).
# The JobControl/JobExecution builders + ExecutionPolicy/edges live in
# control.py / execution.py so the API never imports the engine.


# ---------------------------------------------------------------------------
# Deps — no domain client; nodes are pure computation
# ---------------------------------------------------------------------------

@dataclass
class MathQAWorkflowDependencies:
    """Per-run inputs for the math_qa graph.

    `answer_instructions` and `latex_instructions` are pulled from the
    platform `PromptRegistry` at submit time (in `deps_factory`) so
    nodes never carry hardcoded prompt strings — prompts live as
    versioned `instructions/math_qa/*.md` files (deployed via
    `scripts/deploy_prompts.py`) and stay editable through the
    `/prompts` API.
    """
    question_text: str
    topic: Optional[str] = None
    answer_instructions: Optional[str] = None
    latex_instructions: Optional[str] = None
    figure_instructions: Optional[str] = None
    # Per-run logger bound to this job_id. Defaults to NullLogger when
    # the deps_factory is invoked outside the runner (e.g. tests).
    logger: WorkerLogger = field(default_factory=NullLogger)


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

@dataclass
class ReceiveQuestionStep(BaseNode[MathQAState, MathQAWorkflowDependencies]):
    stage_label = "Receive question"
    stage_description = "Parse and store the incoming math question"

    async def run(self, ctx: GraphRunContext[MathQAState, MathQAWorkflowDependencies]) -> GenerateAnswerStep:
        log = ctx.deps.logger.for_stage("ReceiveQuestionStep")
        await log.info(f"hello from worker — received question: {ctx.deps.question_text!r}")
        ctx.state.question = MathQuestion(
            question_text=ctx.deps.question_text,
            topic=ctx.deps.topic,
        )
        return GenerateAnswerStep()


@dataclass
class GenerateAnswerStep(BaseNode[MathQAState, MathQAWorkflowDependencies]):
    stage_label = "AI answer"
    stage_description = "Generate an AI answer to the math question"

    async def run(self, ctx: GraphRunContext[MathQAState, MathQAWorkflowDependencies]) -> "DecideFigureStep":
        log = ctx.deps.logger.for_stage("GenerateAnswerStep")
        await log.info("calling LLM for plain-text answer…")
        agent = basic_agent(
            output_type=GeneratedAnswer,
            instructions=ctx.deps.answer_instructions,
            retries=2,
        )
        result = await agent.run(user_prompt=ctx.state.question.question_text)
        ctx.state.ai_response = result.output
        await log.info(f"answer received ({len(result.output.answer_text)} chars, {len(result.output.reasoning_steps)} reasoning steps)")
        return DecideFigureStep()


@dataclass
class DecideFigureStep(BaseNode[MathQAState, MathQAWorkflowDependencies]):
    """Control-logic classifier: would a textbook-style figure help?

    Pure routing — uses Haiku (fast / cheap), no system instructions
    (the question is small enough), output is a single boolean.
    The full figure prompt + few-shots only get loaded for the
    rendering step if we branch yes.

    Per AGENTS.md the rule is "no inline prompts in graph nodes" — the
    one-sentence message here is *control logic*, not a domain prompt
    in the registered sense. If this grows beyond a sentence, promote
    it to `instructions/math_qa/figure_decide.md`.
    """
    stage_label = "Figure?"
    stage_description = "Heuristically decide whether to attach a figure to the answer"

    async def run(
        self, ctx: GraphRunContext[MathQAState, MathQAWorkflowDependencies]
    ) -> "RenderFigureStep | GenerateLatexStep":
        log = ctx.deps.logger.for_stage("DecideFigureStep")
        if ctx.state.ai_response is None:
            await log.warning("no AI response on state — skipping figure decision")
            ctx.state.figure_needed = False
            return GenerateLatexStep()

        agent = basic_agent(
            model="claude-haiku-4-5-20251001",
            output_type=FigureDecision,
            retries=1,
        )
        prompt = (
            "Would a small textbook-style topology / differential-geometry "
            "figure (manifold chart, open cover, commutative diagram, etc.) "
            "help a learner understand the following answer? Respond only "
            "with a boolean.\n\n"
            f"Answer:\n{ctx.state.ai_response.answer_text}"
        )
        try:
            result = await agent.run(user_prompt=prompt)
            decision = bool(result.output.needed)
        except Exception as exc:
            # Best-effort: if the classifier fails, skip the figure.
            await log.warning(f"figure classifier failed: {exc!r} — skipping")
            ctx.state.figure_needed = False
            return GenerateLatexStep()

        ctx.state.figure_needed = decision
        await log.info(f"figure decision: {'YES' if decision else 'no'}")
        return RenderFigureStep() if decision else GenerateLatexStep()


@dataclass
class RenderFigureStep(BaseNode[MathQAState, MathQAWorkflowDependencies]):
    stage_label = "Render figure"
    stage_description = (
        "Generate a Munkres/Lee/Tu-style figure JSON via the validate_figure tool"
    )

    async def run(
        self, ctx: GraphRunContext[MathQAState, MathQAWorkflowDependencies]
    ) -> "GenerateLatexStep":
        log = ctx.deps.logger.for_stage("RenderFigureStep")
        if ctx.state.ai_response is None:
            await log.warning("no AI response on state — skipping figure render")
            return GenerateLatexStep()
        await log.info("generating figure spec with validate_figure tool loop…")
        agent = basic_agent(
            output_type=FigureOutput,
            instructions=ctx.deps.figure_instructions,
            tools=[Tool(validate_figure)],
            retries=2,
        )
        prompt = (
            f"Question:\n{ctx.state.question.question_text if ctx.state.question else ''}\n\n"
            f"Answer:\n{ctx.state.ai_response.answer_text}\n\n"
            "Produce one figure that best illustrates the concept."
        )
        try:
            result = await agent.run(user_prompt=prompt)
            ctx.state.figure_output = result.output
            template = result.output.spec.get("template", "?") if isinstance(result.output.spec, dict) else "?"
            await log.info(
                f"figure validated (template={template!r}, "
                f"{result.output.validation_attempts} attempt(s))"
            )
        except Exception as exc:
            await log.error(f"figure render failed: {exc!r} — continuing without figure")
        return GenerateLatexStep()


@dataclass
class GenerateLatexStep(BaseNode[MathQAState, MathQAWorkflowDependencies]):
    stage_label = "Render LaTeX"
    stage_description = (
        "Convert the AI answer into KaTeX-validated LaTeX via the validate_latex tool"
    )

    async def run(self, ctx: GraphRunContext[MathQAState, MathQAWorkflowDependencies]) -> End[None]:
        log = ctx.deps.logger.for_stage("GenerateLatexStep")
        if ctx.state.ai_response is None:
            await log.warning("no AI response on state — skipping LaTeX render")
            return End(None)
        await log.info("rendering LaTeX with validate_latex tool loop…")
        agent = basic_agent(
            output_type=LatexAnswer,
            instructions=ctx.deps.latex_instructions,
            tools=[Tool(validate_latex)],
            retries=2,
        )
        result = await agent.run(user_prompt=ctx.state.ai_response.answer_text)
        ctx.state.latex_answer = result.output
        await log.info(f"LaTeX validated after {result.output.validation_attempts} attempt(s)")
        return End(None)


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

math_qa_graph = Graph(
    nodes=(
        ReceiveQuestionStep,
        GenerateAnswerStep,
        DecideFigureStep,
        RenderFigureStep,
        GenerateLatexStep,
    ),
    state_type=MathQAState,
)

math_qa_node_registry: dict[str, type] = {
    "ReceiveQuestionStep": ReceiveQuestionStep,
    "GenerateAnswerStep": GenerateAnswerStep,
    "DecideFigureStep": DecideFigureStep,
    "RenderFigureStep": RenderFigureStep,
    "GenerateLatexStep": GenerateLatexStep,
}


# ---------------------------------------------------------------------------
# Result extraction (used as the in-record preview payload).
# ---------------------------------------------------------------------------

def _extract_math_qa_result(state: MathQAState) -> MathQAResult:
    """Cheap preview built from in-state values, not from artifacts.

    This is what gets stored on `record.state.result_payload`. The
    canonical result is rebuilt by `_fetch_result` from the workspace.
    """
    review_raw = state.node_reviews.get("GenerateLatexStep")
    review_artifact = (
        UserCommentArtifact(**UserComment.model_validate(review_raw).model_dump())
        if review_raw
        else None
    )
    question_artifact = (
        MathQuestionArtifact(**state.question.model_dump(exclude={"question_id"}))
        if state.question
        else None
    )
    answer_artifact = (
        GeneratedAnswerArtifact(**state.ai_response.model_dump())
        if state.ai_response
        else None
    )
    latex_artifact = (
        LatexAnswerArtifact(
            latex_source=state.latex_answer.latex_source,
            validation_attempts=state.latex_answer.validation_attempts,
        )
        if state.latex_answer
        else None
    )
    figure_artifact = None
    if state.figure_output is not None:
        spec = state.figure_output.spec
        figure_artifact = FigureArtifact(
            template=str(spec.get("template", "?")) if isinstance(spec, dict) else "?",
            spec=spec if isinstance(spec, dict) else {},
            validation_attempts=state.figure_output.validation_attempts,
        )
    return MathQAResult(
        question=question_artifact,
        ai_response=answer_artifact,
        latex=latex_artifact,
        figure=figure_artifact,
        review=review_artifact,
        artifact_refs=list(state.artifact_refs),
    )
