"""Build a CrewAI Agent for one persona of the math_conversation panel.

Loads the persona spec from the prompt registry
([mathai.math_conversation.registry.load_persona]) and its declared
skills, concatenates skill bodies onto the backstory, and returns a
configured `crewai.Agent`. Tools are wired from the union of the
persona's skills' `tool_allowlist`, filtered against the names the
caller actually provides in `tools_by_name` — unknown names (e.g. a
skill that references a not-yet-wired tool) are silently dropped, which
keeps skill authoring decoupled from tool availability.

`crewai` is imported lazily so this module is safe to import from any
runtime (the API, the default worker, tests). Only the crewai-runtime
worker triggers the import by calling `build_agent`.
"""
from __future__ import annotations

import os
from typing import Any

from mathai.math_conversation.registry import load_persona, load_skill

DEFAULT_MODEL = os.getenv("CREW_MODEL", "anthropic/claude-sonnet-4-5-20250929")


def build_agent(
    persona_name: str,
    *,
    tools_by_name: dict[str, Any] | None = None,
    model: str | None = None,
) -> Any:
    """Return a `crewai.Agent` built from `persona_name` + its skills.

    `tools_by_name` maps tool name (as referenced in a skill's
    `tool_allowlist`) to the prebuilt CrewAI tool instance. The agent
    receives only the subset of tools whose names appear in any of its
    skills' allowlists. `conclude` is always implicitly allowed — every
    panelist may end the conversation — and is wired whenever it appears
    in `tools_by_name`.

    `model` overrides the persona's front-matter `model:` field; both
    fall back to `CREW_MODEL` env / `DEFAULT_MODEL`. Per-persona model
    selection is the design's intended hook for putting (say) a stronger
    model on the Synthesist than on a quicker speaker.
    """
    import crewai

    persona = load_persona(persona_name)
    skills = [load_skill(name) for name in persona.skills]

    backstory = persona.body
    if skills:
        backstory = backstory.rstrip() + "\n\n" + "\n\n".join(s.body.rstrip() for s in skills)

    chosen_model = model or persona.model or DEFAULT_MODEL
    llm = crewai.LLM(model=chosen_model)

    available = tools_by_name or {}
    allowed_names = set().union(*(s.tool_allowlist for s in skills)) | {"conclude"}
    tools = [available[name] for name in allowed_names if name in available]

    return crewai.Agent(
        role=persona.role,
        goal=persona.goal,
        backstory=backstory,
        tools=tools,
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )
