"""math_conversation artifacts — the persisted output of a crew run.

Unlike `math_qa`, which mints one artifact per produced value
(question / answer / latex / figure), a conversation produces a single
`MathConversationArtifact` holding the whole transcript. Mid-conversation
LaTeX and figures live **inline on each turn** rather than as separate
artifact-store rows — the math-ui chat renderer consumes them directly
(see `docs/math_conversation.md` → Output shape).

`ConversationTurn` and `ToolCallRecord` are embedded sub-models, not
`BaseArtifact` subclasses: they are never stored or fetched on their
own. The same `ConversationTurn` shape is reused on `MathConversationState`
for the in-flight transcript, so the live and persisted renderers share
one contract.
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_platform.jobs.artifact import BaseArtifact

# The semantic figure spec is an opaque JSON dict everywhere else in the
# codebase (see `math_qa.artifacts.FigureArtifact.spec`); there is no
# dedicated model. Alias it for readability and so the renderer has a
# name to target.
FigureSpec = dict[str, Any]


class ToolCallRecord(BaseModel):
    """One tool invocation an agent made inside a turn."""
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Optional[str] = None


class ConversationTurn(BaseModel):
    """A single agent move in the conversation.

    Embedded in `MathConversationArtifact.turns` and mirrored on
    `MathConversationState.turns` while the run is in flight. `latex`
    and `figure` are inline — the math-ui `<Latex>` component and figure
    renderer take these values directly.
    """
    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(..., ge=0)
    agent_role: str
    agent_persona: str
    content: str
    latex: Optional[str] = None
    figure: Optional[FigureSpec] = None
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    cost_usd: float = Field(default=0.0, ge=0.0)


class MathConversationArtifact(BaseArtifact):
    """The whole brainstorm transcript, persisted once at end-of-run.

    `seed_question` is the question the panel explored — pulled from a
    source `math_qa` job's artifacts or wrapped from fresh input text.
    `source_job_id` records provenance when seeded from a prior job.
    """
    artifact_type: Literal["math_conversation"] = "math_conversation"
    source_job_id: Optional[UUID] = None
    seed_question: str
    turns: List[ConversationTurn] = Field(default_factory=list)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    stop_reason: Literal["max_turns", "concluded"] = "max_turns"


MATH_CONVERSATION_ARTIFACTS: dict[str, type[BaseArtifact]] = {
    MathConversationArtifact.model_fields["artifact_type"].default: MathConversationArtifact,
}
