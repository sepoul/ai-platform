"""Math Q&A graph state.

The legacy `MathQARun`/`MathQAStore` were retired when artifacts became
first-class outputs (see NEXT_BEST_STEPS.md #1). Execution state lives
on the platform's `JobRecord` (with its checkpoints); produced data
lives in the workspace artifact store.
"""
from __future__ import annotations

from typing import Optional

from mathai.math_qa.models import (
    FigureOutput,
    GeneratedAnswer,
    LatexAnswer,
    MathQuestion,
)
from ai_platform.jobs.base_state import BaseJobState


class MathQAState(BaseJobState):
    """Pure domain state. Carries transient values during graph execution.

    Question, AI response, validated LaTeX, and (optionally) a figure
    live here only between nodes — once the persistence callback fires
    they are minted into `MathQuestionArtifact` / `GeneratedAnswerArtifact`
    / `LatexAnswerArtifact` / `FigureArtifact` whose IDs land on
    `state.artifact_refs`. Human review lives in `node_reviews`
    (from BaseJobState).

    `figure_needed` is the classifier's decision (set by
    `DecideFigureStep`); `figure_output` is the rendered spec, present
    only when the decision was True and the agent converged.
    """

    question: Optional[MathQuestion] = None
    ai_response: Optional[GeneratedAnswer] = None
    latex_answer: Optional[LatexAnswer] = None
    figure_needed: Optional[bool] = None
    figure_output: Optional[FigureOutput] = None
