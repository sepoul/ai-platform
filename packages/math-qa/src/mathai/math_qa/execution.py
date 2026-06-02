"""math_qa execution plane — `JobExecution` (the graph engine) + `register_execution`.

Imports the pydantic_graph workflow. Only a default-runtime worker (and the
offline workflow-descriptor generator) imports this module.
"""
from __future__ import annotations

from typing import Optional
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
from mathai.math_qa.artifacts import (
    MATH_QA_ARTIFACTS,
    FigureArtifact,
    GeneratedAnswerArtifact,
    LatexAnswerArtifact,
    MathQuestionArtifact,
    UserCommentArtifact,
)
from mathai.math_qa.gates import MATH_QA_GATES
from mathai.math_qa.models import UserComment
from mathai.math_qa.state import MathQAState
from mathai.math_qa.workflow import (
    MathQAWorkflowDependencies,
    _extract_math_qa_result,
    math_qa_graph,
    math_qa_node_registry,
)
from ai_platform.workspace.client import PlatformClient

# Runnable gating, built from the gate list the control plane also exposes.
math_qa_policy = ExecutionPolicy(gates=MATH_QA_GATES)

MATH_QA_EDGES = [
    EdgeSpec("ReceiveQuestionStep", "GenerateAnswerStep", "Question received"),
    EdgeSpec("GenerateAnswerStep", "DecideFigureStep", "Answer generated"),
    EdgeSpec("DecideFigureStep", "RenderFigureStep", "Figure helpful"),
    EdgeSpec("DecideFigureStep", "GenerateLatexStep", "Skip figure"),
    EdgeSpec("RenderFigureStep", "GenerateLatexStep", "Figure rendered"),
    EdgeSpec("GenerateLatexStep", "HumanReviewStep", "Ready for review"),
    EdgeSpec("HumanReviewStep", "End", "Comment received"),
]


def build_math_qa_execution(
    artifact_api: ArtifactService,
    platform_client: PlatformClient,
) -> JobExecution:
    prompt_registry = getattr(platform_client, "prompt_registry", None)

    def _load_prompt(name: str) -> Optional[str]:
        """Best-effort fetch from the prompt registry; None on miss lets
        nodes fall back rather than crashing (useful in bare-bones tests)."""
        if prompt_registry is None:
            return None
        try:
            return prompt_registry.get_prompt(name).instructions
        except Exception:
            return None

    def _deps_factory(payload: dict):
        job_id = payload.get("_job_id")
        logger: WorkerLogger = WorkerLogger(job_id) if job_id else NullLogger()
        return MathQAWorkflowDependencies(
            question_text=payload.get("question_text", ""),
            topic=payload.get("topic"),
            answer_instructions=_load_prompt("math_qa.answer"),
            latex_instructions=_load_prompt("math_qa.latex_render"),
            figure_instructions=_load_prompt("math_qa.figure"),
            logger=logger,
        )

    def _persist(job_id: str, state: MathQAState) -> list[UUID]:
        """Mint any artifacts implied by `state` that don't yet exist.

        Idempotent: inspects existing artifacts referenced by
        `state.artifact_refs` and only mints the ones that are missing.
        """
        existing = artifact_api.get_many(state.artifact_refs) if state.artifact_refs else []
        existing_types = {type(a) for a in existing}
        new_ids: list[UUID] = []

        if state.question is not None and MathQuestionArtifact not in existing_types:
            artifact = MathQuestionArtifact(
                created_by_job=job_id,
                question_text=state.question.question_text,
                topic=state.question.topic,
                difficulty=state.question.difficulty,
            )
            artifact_api.put(artifact)
            new_ids.append(artifact.artifact_id)

        if state.ai_response is not None and GeneratedAnswerArtifact not in existing_types:
            artifact = GeneratedAnswerArtifact(
                created_by_job=job_id,
                answer_text=state.ai_response.answer_text,
                reasoning_steps=state.ai_response.reasoning_steps,
                confidence=state.ai_response.confidence,
                model_used=state.ai_response.model_used,
            )
            artifact_api.put(artifact)
            new_ids.append(artifact.artifact_id)

        if state.latex_answer is not None and LatexAnswerArtifact not in existing_types:
            artifact = LatexAnswerArtifact(
                created_by_job=job_id,
                latex_source=state.latex_answer.latex_source,
                validation_attempts=state.latex_answer.validation_attempts,
            )
            artifact_api.put(artifact)
            new_ids.append(artifact.artifact_id)

        if state.figure_output is not None and FigureArtifact not in existing_types:
            spec = state.figure_output.spec if isinstance(state.figure_output.spec, dict) else {}
            artifact = FigureArtifact(
                created_by_job=job_id,
                template=str(spec.get("template", "?")),
                spec=spec,
                validation_attempts=state.figure_output.validation_attempts,
            )
            artifact_api.put(artifact)
            new_ids.append(artifact.artifact_id)

        review_raw = state.node_reviews.get("GenerateLatexStep")
        if review_raw and UserCommentArtifact not in existing_types:
            comment = UserComment.model_validate(review_raw)
            artifact = UserCommentArtifact(
                created_by_job=job_id,
                comment_text=comment.comment_text,
                rating=comment.rating,
                is_correct=comment.is_correct,
            )
            artifact_api.put(artifact)
            new_ids.append(artifact.artifact_id)

        return new_ids

    return JobExecution(
        name="math_qa",
        graph=math_qa_graph,
        state_type=MathQAState,
        start_node_key="ReceiveQuestionStep",
        node_registry=math_qa_node_registry,
        deps_factory=_deps_factory,
        extract_result=_extract_math_qa_result,
        policy=math_qa_policy,
        persistence=PersistencePolicy(on_complete=_persist, on_pause=_persist),
        edges=MATH_QA_EDGES,
    )


def register_execution(ctx: BootstrapContext) -> ExecutionDomain:
    return ExecutionDomain(
        name="math_qa",
        job_executions=[build_math_qa_execution(ctx.artifact_service, ctx.platform_client)],
        artifact_types=list(MATH_QA_ARTIFACTS.values()),
    )
