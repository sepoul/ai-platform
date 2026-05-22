"""Crew → UI chat events (MSN-Messenger-2007 styling).

`CrewChatEvent` is the structured event the chat renderer consumes. The
events ride the *existing* worker→UI log stream: `CrewChatEmitter`
serializes each event to JSON and pushes it through `WorkerLogger.emit`,
tagged `source="crew_chat"` so the math-ui live parser can pick crew
events out of ordinary log lines (plain logs don't JSON-parse to an
object with an `event` key).

This module is deliberately CrewAI-free: the emitters take a
`WorkerLogger` and can be unit-tested by hand-firing events at a fake
logger. T5 wires CrewAI's `step_callback` to call these.
"""
from __future__ import annotations

import time
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_platform.runtime.worker_log import WorkerLogger


CrewChatEventName = Literal[
    "signed_in",    # agent joined the conversation
    "is_typing",    # agent is preparing a response
    "message",      # agent emitted a turn
    "tool_call",    # agent invoked a tool
    "tool_result",  # tool returned
    "concluded",    # agent called conclude()
    "signed_out",   # crew run finished
    "status",       # budget / cost rollup snapshot
]

CREW_CHAT_SOURCE = "crew_chat"


# Maps raw tool names to human-friendly "is doing X" phrases for the chat
# status line ("Algebraist is checking the LaTeX…"). Unknown tools fall
# back to their raw name.
FRIENDLY_TOOL_NAMES: dict[str, str] = {
    "validate_latex": "checking the LaTeX",
    "validate_figure": "sketching the figure",
    "conclude": "wrapping up",
}


def friendly_tool_name(tool_name: str) -> str:
    return FRIENDLY_TOOL_NAMES.get(tool_name, tool_name)


class CrewChatEvent(BaseModel):
    """One event in the live conversation stream.

    Mirrors `docs/math_conversation.md` → Live visibility. Optional
    fields are populated per event kind (e.g. `content` on `message`,
    `tool_name` on `tool_call`).
    """
    model_config = ConfigDict(extra="forbid")

    event: CrewChatEventName
    agent_role: Optional[str] = None
    display_name: Optional[str] = None
    turn_index: Optional[int] = None
    content: Optional[str] = None
    latex: Optional[str] = None
    tool_name: Optional[str] = None
    elapsed_seconds: float = 0.0
    turns_used: Optional[int] = None
    turns_budget: Optional[int] = None
    cost_usd: Optional[float] = None


def crew_chat_logger(logger: WorkerLogger) -> WorkerLogger:
    """Return a `crew_chat`-sourced sibling of `logger`.

    The UI distinguishes crew events from ordinary worker logs by this
    `source` tag. `NullLogger` is returned unchanged (it drops everything
    anyway), and any non-`WorkerLogger` (e.g. a test fake) is passed
    through untouched so it stays observable in tests.
    """
    if type(logger) is WorkerLogger:
        return WorkerLogger(job_id=logger.job_id, stage=logger.stage, source=CREW_CHAT_SOURCE)
    return logger


class CrewChatEmitter:
    """Fires `CrewChatEvent`s through a `WorkerLogger`.

    Carries the run start time (for `elapsed_seconds`) and the turn budget
    so individual call sites stay terse. Construct one per crew run; pass
    a job-bound `WorkerLogger` (or `NullLogger` in tests/standalone). The
    logger's `source` is re-tagged to `crew_chat` (see `crew_chat_logger`),
    except for test fakes, which are used as-is.
    """

    def __init__(
        self,
        logger: WorkerLogger,
        *,
        turns_budget: Optional[int] = None,
        start: Optional[float] = None,
    ) -> None:
        self._logger = crew_chat_logger(logger)
        self._turns_budget = turns_budget
        self._start = start if start is not None else time.monotonic()

    def _elapsed(self) -> float:
        return round(time.monotonic() - self._start, 3)

    async def _emit(self, event: CrewChatEvent) -> CrewChatEvent:
        await self._logger.emit(event.model_dump_json())
        return event

    async def emit_signed_in(self, agent_role: str, display_name: str) -> CrewChatEvent:
        return await self._emit(CrewChatEvent(
            event="signed_in", agent_role=agent_role, display_name=display_name,
            turns_budget=self._turns_budget, elapsed_seconds=self._elapsed(),
        ))

    async def emit_typing(self, agent_role: str, display_name: str) -> CrewChatEvent:
        return await self._emit(CrewChatEvent(
            event="is_typing", agent_role=agent_role, display_name=display_name,
            elapsed_seconds=self._elapsed(),
        ))

    async def emit_message(
        self,
        agent_role: str,
        display_name: str,
        turn_index: int,
        content: str,
        *,
        latex: Optional[str] = None,
        cost_usd: Optional[float] = None,
    ) -> CrewChatEvent:
        return await self._emit(CrewChatEvent(
            event="message", agent_role=agent_role, display_name=display_name,
            turn_index=turn_index, content=content, latex=latex, cost_usd=cost_usd,
            elapsed_seconds=self._elapsed(),
        ))

    async def emit_tool_call(
        self, agent_role: str, display_name: str, tool_name: str
    ) -> CrewChatEvent:
        return await self._emit(CrewChatEvent(
            event="tool_call", agent_role=agent_role, display_name=display_name,
            tool_name=tool_name, elapsed_seconds=self._elapsed(),
        ))

    async def emit_tool_result(
        self, agent_role: str, display_name: str, tool_name: str
    ) -> CrewChatEvent:
        return await self._emit(CrewChatEvent(
            event="tool_result", agent_role=agent_role, display_name=display_name,
            tool_name=tool_name, elapsed_seconds=self._elapsed(),
        ))

    async def emit_concluded(
        self, agent_role: str, display_name: str, *, content: Optional[str] = None
    ) -> CrewChatEvent:
        return await self._emit(CrewChatEvent(
            event="concluded", agent_role=agent_role, display_name=display_name,
            content=content, elapsed_seconds=self._elapsed(),
        ))

    async def emit_signed_out(self, agent_role: str, display_name: str) -> CrewChatEvent:
        return await self._emit(CrewChatEvent(
            event="signed_out", agent_role=agent_role, display_name=display_name,
            elapsed_seconds=self._elapsed(),
        ))

    async def emit_status(
        self, *, turns_used: int, cost_usd: float
    ) -> CrewChatEvent:
        return await self._emit(CrewChatEvent(
            event="status", turns_used=turns_used, turns_budget=self._turns_budget,
            cost_usd=cost_usd, elapsed_seconds=self._elapsed(),
        ))
