"""Math Q&A artifacts — pure data the job produces."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import Field

from ai_platform.jobs.artifact import BaseArtifact


class MathQuestionArtifact(BaseArtifact):
    artifact_type: Literal["math_question"] = "math_question"
    question_text: str
    topic: Optional[str] = None
    difficulty: Optional[str] = None


class GeneratedAnswerArtifact(BaseArtifact):
    artifact_type: Literal["ai_answer"] = "ai_answer"
    answer_text: str
    reasoning_steps: List[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    model_used: Optional[str] = None


class UserCommentArtifact(BaseArtifact):
    artifact_type: Literal["user_comment"] = "user_comment"
    comment_text: str
    rating: Optional[int] = Field(None, ge=1, le=5)
    is_correct: Optional[bool] = None


class FigureArtifact(BaseArtifact):
    """Validated semantic figure spec (Munkres / Lee / Tu style).

    Produced by `RenderFigureStep` after the agent has converged on
    a structurally valid spec via the `validate_figure` tool. The
    `spec` is an opaque JSON payload — the FEATURES.md plan calls
    for keeping it as `dict[str, Any]` server-side; the renderer
    contract lives in `math-ui`. `template` is duplicated out of the
    spec for indexable filtering.
    """
    artifact_type: Literal["figure"] = "figure"
    template: str = Field(..., description="Top-level template name (also at spec['template']).")
    spec: dict = Field(..., description="The validated semantic figure spec — opaque JSON.")
    validation_attempts: int = Field(default=1, ge=1)


class LatexAnswerArtifact(BaseArtifact):
    """Validated LaTeX rendering of an AI answer.

    Produced by `GenerateLatexStep` after the agent has converged on
    KaTeX-compilable source via the `validate_latex` tool. `is_valid`
    is always True at persistence time — invalid drafts never escape
    the validation loop. `validation_attempts` records how many
    rounds of tool feedback the agent took to converge.
    """
    artifact_type: Literal["latex_answer"] = "latex_answer"
    latex_source: str = Field(..., description="KaTeX-compilable LaTeX body.")
    is_valid: bool = True
    validation_attempts: int = Field(default=1, ge=1)


MATH_QA_ARTIFACTS: dict[str, type[BaseArtifact]] = {
    MathQuestionArtifact.model_fields["artifact_type"].default: MathQuestionArtifact,
    GeneratedAnswerArtifact.model_fields["artifact_type"].default: GeneratedAnswerArtifact,
    UserCommentArtifact.model_fields["artifact_type"].default: UserCommentArtifact,
    LatexAnswerArtifact.model_fields["artifact_type"].default: LatexAnswerArtifact,
    FigureArtifact.model_fields["artifact_type"].default: FigureArtifact,
}
