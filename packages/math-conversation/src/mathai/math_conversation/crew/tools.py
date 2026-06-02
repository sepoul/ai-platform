"""Tools agents in the math_conversation panel can call.

`conclude` is the only tool wired in v1: it lets any persona declare the
discussion has reached a natural close, short-circuiting the turn loop
before `max_turns`. The tool flips a `ConcludeSignal` captured in its
closure; `RunCrewStep` reads the signal after each turn and mirrors it
to `state.concluded`.

`validate_latex` / `validate_figure` adapters around the math_qa tools
([math_qa/tools.py]) are deliberate follow-ups — wiring them requires
sync-wrapping the existing async httpx calls and is independent of the
panel work. Skill files (e.g. `symbolic-manipulation.md`) may already
list them in `tool_allowlist`; `build_agent` filters unknown names so an
unwired allowlist entry is harmless.

CrewAI is imported lazily inside `build_conclude_tool` — only the
crewai-runtime worker installs it, and the rest of this module stays
importable from any runtime (API, default worker, tests).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ConcludeSignal:
    """Closure-captured flag flipped by the `conclude` tool.

    `RunCrewStep` constructs one signal per panel run, captures it in the
    tool's closure, and reads it after each turn. Mutating a single
    object lets the tool (called from CrewAI's tool-execution path) and
    the turn loop (running in the worker's asyncio task) communicate
    without smuggling state through CrewAI internals.
    """

    fired: bool = False
    reason: str = ""


def _make_conclude_runner(signal: ConcludeSignal) -> Callable[[str], str]:
    """Build the pure-Python body of the conclude tool.

    Split out so the closure behavior (flipping `signal`) can be
    unit-tested without importing `crewai`.
    """

    def run(reason: str = "") -> str:
        signal.fired = True
        signal.reason = reason
        return f"Concluded: {reason}" if reason else "Concluded."

    return run


def build_conclude_tool(signal: ConcludeSignal) -> Any:
    """Return a `crewai.tools.BaseTool` that flips `signal` when invoked.

    The returned tool's `_run` delegates to the closure built by
    `_make_conclude_runner`, so the import-light path stays testable
    and the crewai-dependent path stays minimal. Imports `crewai`
    lazily — callers in the crewai runtime trigger the import.
    """
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field

    runner = _make_conclude_runner(signal)

    class _ConcludeArgs(BaseModel):
        reason: str = Field(
            default="",
            description="Short reason why the discussion has reached a natural close.",
        )

    class ConcludeTool(BaseTool):
        name: str = "conclude"
        description: str = (
            "Call when the panel has explored the question thoroughly and the "
            "discussion has reached a natural close. Provide a short `reason` "
            "explaining why the conversation is complete. Once any panelist "
            "calls this, the conversation ends."
        )
        args_schema: type[BaseModel] = _ConcludeArgs

        def _run(self, reason: str = "") -> str:
            return runner(reason)

    return ConcludeTool()
