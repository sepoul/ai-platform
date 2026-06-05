"""math_qa control plane — `JobControl` (schemas) + `register_control`.

Engine-free on purpose: imports models/artifacts only, never the
pydantic_graph workflow. The API imports this for every domain, so it must
not pull the graph engine. The execution plane lives in `execution.py`.
"""
from __future__ import annotations

from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.jobs.domain import BootstrapContext, ControlDomain
from ai_platform.jobs.execution_policy import JobControl
from ai_platform.jobs.result_fetcher import hydrate_artifact_refs
from mathai.math_qa.artifacts import (
    MATH_QA_ARTIFACTS,
    FigureArtifact,
    GeneratedAnswerArtifact,
    LatexAnswerArtifact,
    MathQuestionArtifact,
    UserCommentArtifact,
)
from mathai.math_qa.gates import MATH_QA_GATES
from mathai.math_qa.models import MathQAInput, MathQAResult


def build_math_qa_control(artifact_api: ArtifactService) -> JobControl:
    def _fetch_result(record) -> MathQAResult:
        artifacts = hydrate_artifact_refs(record, artifact_api)
        question = next((a for a in artifacts if isinstance(a, MathQuestionArtifact)), None)
        answer = next((a for a in artifacts if isinstance(a, GeneratedAnswerArtifact)), None)
        latex = next((a for a in artifacts if isinstance(a, LatexAnswerArtifact)), None)
        figure = next((a for a in artifacts if isinstance(a, FigureArtifact)), None)
        review = next((a for a in artifacts if isinstance(a, UserCommentArtifact)), None)
        return MathQAResult(
            question=question,
            ai_response=answer,
            latex=latex,
            figure=figure,
            review=review,
            artifact_refs=[a.artifact_id for a in artifacts],
        )

    return JobControl(
        name="math_qa",
        label="math_qa_graph",
        submit_input_type=MathQAInput,
        result_type=MathQAResult,
        gates=MATH_QA_GATES,
        fetch_result=_fetch_result,
    )


def register_control(ctx: BootstrapContext) -> ControlDomain:
    return ControlDomain(
        name="math_qa",
        job_controls=[build_math_qa_control(ctx.artifact_service)],
        artifact_types=list(MATH_QA_ARTIFACTS.values()),
        runtime_selector="default",
        code_entrypoint="mathai.math_qa.execution:register_execution",
        control_entrypoint="mathai.math_qa.control:register_control",
    )
