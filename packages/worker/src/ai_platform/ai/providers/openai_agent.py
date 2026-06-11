"""OpenAI-powered agent factory — the OpenAI sibling of [[basic_agent]].

`basic_agent` builds a pydantic_ai `Agent` on an `AnthropicModel`; this builds
the *same shape* on an `OpenAIModel`, so a domain can pick a provider per node
without changing how it constructs or runs the agent. Same return type
(`pydantic_ai.Agent`), same `output_type` / `toolsets` / `tools` / `retries`
wiring — only the backing model differs.

The `openai` SDK ships in the **worker base** (present in both runtimes); the
pydantic_ai framework is the `default` runtime's stack. So this factory is a
`default`-runtime helper: the SDK is always there, and `OpenAIModel` resolves
wherever pydantic_ai is. Imports are deferred into the factory body so merely
importing this module never drags pydantic_ai into a base/control process.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pydantic_ai import Agent, FunctionToolset, Tool


_logfire_instrumented = False


def _instrument_logfire_once() -> None:
    """Best-effort tracing, matching `basic_agent`'s Logfire instrumentation.

    Soft-fail: if Logfire isn't installed or isn't configured (no token), the
    agent still works untraced — tracing is an observability nicety, never a
    hard requirement for building an agent.
    """
    global _logfire_instrumented
    if _logfire_instrumented:
        return
    try:
        import logfire

        logfire.configure()
        logfire.instrument_pydantic_ai()
    except Exception:
        pass
    # Set regardless: a failed attempt shouldn't retry (and re-log) per call.
    _logfire_instrumented = True


def openai_agent(
    model: str = "gpt-4o",
    output_type=None,
    instructions: Optional[str] = None,
    toolsets: "Optional[List[FunctionToolset]]" = None,
    tools: "Optional[List[Tool]]" = None,
    retries: int = 1,
) -> "Agent":
    """Create a pydantic_ai `Agent` backed by an `OpenAIModel`.

    Mirrors `basic_agent` field-for-field; only the model provider differs.
    The `openai` SDK is in the worker base; this needs the `default` runtime
    for pydantic_ai (the same stack `basic_agent` uses).
    """
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIModel

    _instrument_logfire_once()

    return Agent[None, output_type](
        OpenAIModel(model),
        output_type=output_type,
        toolsets=toolsets or [],
        tools=tools or [],
        retries=retries,
        instructions=instructions,
    )
