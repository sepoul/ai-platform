"""Build a CrewAI Agent for a persona.

Micro version of T5: loads the persona spec from the prompt registry
(`mathai.math_conversation.registry.load_persona`) and wraps it in a
`crewai.Agent` with an Anthropic LLM. Skill loading + tool-allowlist
enforcement land in the full T5; this builder ignores skills for now.

Imports `crewai` lazily — the only callers are the worker[crewai] image
(at runtime) and the descriptor generator (which never calls in here).
"""
from __future__ import annotations

import os
from typing import Any

from mathai.math_conversation.registry import load_persona

DEFAULT_MODEL = os.getenv("CREW_MODEL", "anthropic/claude-sonnet-4-5-20250929")


def build_agent(persona_name: str, *, model: str = DEFAULT_MODEL) -> Any:
    """Return a `crewai.Agent` from a persona spec. `model` defaults to
    Anthropic via CrewAI's native provider; the SDK is present in the
    worker[crewai] image via `pydantic-ai-slim[anthropic]`.
    """
    import crewai  # lazy: only the crewai-runtime worker installs it

    persona = load_persona(persona_name)
    llm = crewai.LLM(model=model)
    return crewai.Agent(
        role=persona.role,
        goal=persona.goal,
        backstory=persona.body,  # PersonaSpec.body is the agent backstory
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )
