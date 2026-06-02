"""
Math Q&A data models.

Simple flow: user asks a math question → AI responds → user comments.
"""
from __future__ import annotations

from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.result import BaseJobResult
from mathai.math_qa.artifacts import (
    FigureArtifact,
    GeneratedAnswerArtifact,
    LatexAnswerArtifact,
    MathQuestionArtifact,
    UserCommentArtifact,
)


class MathQuestion(BaseModel):
    """A math question submitted by a user."""
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(default_factory=lambda: uuid4().hex)
    question_text: str = Field(..., description="The math question in natural language.")
    topic: Optional[str] = Field(None, description="E.g. algebra, calculus, geometry.")
    difficulty: Optional[str] = Field(None, description="E.g. easy, medium, hard.")


class GeneratedAnswer(BaseModel):
    """AI-generated answer to a math question."""
    model_config = ConfigDict(extra="forbid")

    answer_text: str = Field(..., description="The AI's answer/solution.")
    reasoning_steps: List[str] = Field(default_factory=list, description="Step-by-step reasoning.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    model_used: Optional[str] = None


class LatexAnswer(BaseModel):
    """Output type for the LaTeX-rendering agent.

    The agent produces this AFTER calling `validate_latex` on
    `latex_source` and getting `valid=true`. `validation_attempts`
    counts the tool calls the agent made before converging.
    """
    model_config = ConfigDict(extra="forbid")

    latex_source: str = Field(..., description="KaTeX-compilable LaTeX body.")
    validation_attempts: int = Field(
        default=1, ge=1,
        description="How many validate_latex calls the agent made before converging.",
    )


class FigureOutput(BaseModel):
    """Output type for the figure-rendering agent.

    `spec` is the semantic figure JSON validated against the renderer
    contract (templates / object types / relation types — see
    `instructions/math_qa/figure.md`). `validation_attempts` counts
    the tool calls the agent made before converging.
    """
    model_config = ConfigDict(extra="forbid")

    spec: dict = Field(..., description="Semantic figure spec consumed by the math-ui renderer.")
    validation_attempts: int = Field(default=1, ge=1)


class FigureDecision(BaseModel):
    """Output type for the small classifier that decides whether the
    answer would benefit from a figure. Pure control logic — kept tiny
    so a fast model can answer in a single token."""
    model_config = ConfigDict(extra="forbid")

    needed: bool = Field(..., description="True iff a figure would help the learner understand.")


class UserComment(BaseModel):
    """User feedback on an AI response."""
    model_config = ConfigDict(extra="forbid")

    comment_text: str
    rating: Optional[int] = Field(None, ge=1, le=5, description="1-5 star rating.")
    is_correct: Optional[bool] = Field(None, description="Did the user mark the answer correct?")


class MathQAInput(BaseJobInput):
    """Typed submit input for a Math Q&A job — variant of the platform request union."""

    job_type: Literal["math_qa"] = "math_qa"
    question_text: str = Field(..., description="The math question.")
    topic: Optional[str] = Field(None, description="E.g. algebra, calculus.")
    created_by: Optional[str] = Field(None, description="Submitting user.")


class MathQAResult(BaseJobResult):
    """Typed result for a Math Q&A job — variant of the platform result union.

    Each typed field is an artifact resolved from `artifact_refs` (defined
    on `BaseJobResult`). The result endpoint hydrates them via the
    workspace artifact store.
    """

    job_type: Literal["math_qa"] = "math_qa"
    question: Optional[MathQuestionArtifact] = None
    ai_response: Optional[GeneratedAnswerArtifact] = None
    latex: Optional[LatexAnswerArtifact] = None
    figure: Optional[FigureArtifact] = None
    review: Optional[UserCommentArtifact] = None
