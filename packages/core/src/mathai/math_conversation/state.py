"""math_conversation graph state.

Like `math_qa`, execution state lives on the platform `JobRecord`
(checkpoints) while produced data becomes a workspace artifact. This
carries the transient values the three nodes pass between each other:
the resolved seed, the accumulating transcript, and the running cost.
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional
from uuid import UUID

from ai_platform.jobs.base_state import BaseJobState
from mathai.math_conversation.artifacts import ConversationTurn


class MathConversationState(BaseJobState):
    """Pure domain state for one conversation run.

    `seed_question` is the resolved question the panel explores (set by
    `SeedStep`). `seed_context` holds the projected artifacts from a
    source `math_qa` job (answer / latex / figure) when seeded, else None.
    `turns` accumulates each agent move; `cost_so_far` is the running
    token cost. `concluded` is flipped by the `conclude` tool so
    `RunCrewStep` can short-circuit; `stop_reason` records why the loop
    ended.
    """

    source_job_id: Optional[UUID] = None
    seed_question: Optional[str] = None
    seed_context: Optional[dict[str, Any]] = None
    max_turns: int = 12
    turns: List[ConversationTurn] = []
    cost_so_far: float = 0.0
    concluded: bool = False
    stop_reason: Optional[Literal["max_turns", "concluded"]] = None
