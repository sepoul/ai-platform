"""math_conversation data models — submit input, typed result, and the
persona/skill specs the crew is built from.

The crew runs on **OpenAI** models via CrewAI's native OpenAI provider
(see `docs/math_conversation.md` → Dependency strategy): a deliberately
different provider from `math_qa` (Anthropic via pydantic_ai), so the two
domains share no LLM-SDK version constraint.
"""
from __future__ import annotations

from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self

from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.result import BaseJobResult
from mathai.math_conversation.artifacts import MathConversationArtifact


class MathConversationInput(BaseJobInput):
    """Typed submit input — a variant of the platform request union.

    Exactly one of `source_job_id` (seed from a completed `math_qa` job)
    or `question_text` (fresh question) must be set; the validator
    rejects "both" and "neither" at the API boundary.
    """

    job_type: Literal["math_conversation"] = "math_conversation"
    source_job_id: Optional[UUID] = Field(
        None, description="Seed from a completed math_qa job's artifacts."
    )
    question_text: Optional[str] = Field(
        None, description="Fresh question to brainstorm (when not seeding from a job)."
    )
    max_turns: int = Field(
        default=12, ge=1, le=30, description="Hard cap on conversation turns."
    )
    created_by: Optional[str] = Field(None, description="Submitting user.")

    @model_validator(mode="after")
    def exactly_one_source(self) -> Self:
        if bool(self.source_job_id) == bool(self.question_text):
            raise ValueError(
                "Provide exactly one of source_job_id or question_text."
            )
        return self


class MathConversationResult(BaseJobResult):
    """Typed result — a variant of the platform result union.

    The single `conversation` artifact is resolved from `artifact_refs`
    by the result endpoint's hydrator.
    """

    job_type: Literal["math_conversation"] = "math_conversation"
    conversation: Optional[MathConversationArtifact] = None


class PersonaSpec(BaseModel):
    """A panel member, parsed from `instructions/math_conversation/personae/<name>.md`.

    Front-matter carries the structured fields; the Markdown body becomes
    the agent's CrewAI `backstory`. `model` is an OpenAI model id.
    """
    model_config = ConfigDict(extra="forbid")

    name: str
    role: str
    goal: str
    display_name: str
    model: str
    skills: List[str] = Field(default_factory=list)
    body: str = ""


class SkillSpec(BaseModel):
    """A reusable skill, parsed from `instructions/math_conversation/skills/<name>.md`.

    The body is appended to a persona's backstory at agent-build time;
    `tool_allowlist` constrains which tools an agent carrying this skill
    may call.
    """
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    tool_allowlist: List[str] = Field(default_factory=list)
    body: str = ""
