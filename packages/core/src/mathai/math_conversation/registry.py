"""Persona / skill loading for the math_conversation domain.

The platform prompt registry stores personae and skills as `Prompt`
entries (`kind="persona"` / `"skill"`) whose `instructions` hold the full
Markdown (YAML front-matter + body). The *interpretation* of that
front-matter into typed `PersonaSpec` / `SkillSpec` is domain knowledge,
so it lives here — `ai_platform` only provides the generic
`parse_frontmatter` splitter.

`load_persona` / `load_skill` read straight from the on-disk
`instructions/math_conversation/...` files; `parse_persona` /
`parse_skill` parse an already-loaded Markdown string (e.g. fetched from
the `/prompts` API).
"""
from __future__ import annotations

from pathlib import Path

from ai_platform.ai.prompts.registry import parse_frontmatter
from ai_platform.utilities.paths import find_ancestor_containing
from mathai.math_conversation.models import PersonaSpec, SkillSpec

_INSTRUCTIONS_DIR = find_ancestor_containing("instructions") / "instructions"
_DOMAIN = "math_conversation"


def parse_persona(markdown: str, name: str) -> PersonaSpec:
    meta, body = parse_frontmatter(markdown)
    if meta.get("kind") != "persona":
        raise ValueError(f"persona {name!r} front-matter missing `kind: persona`")
    return PersonaSpec(
        name=name,
        role=meta["role"],
        goal=meta["goal"],
        display_name=meta.get("display_name", meta["role"]),
        model=meta["model"],
        skills=list(meta.get("skills", []) or []),
        body=body,
    )


def parse_skill(markdown: str, name: str) -> SkillSpec:
    meta, body = parse_frontmatter(markdown)
    if meta.get("kind") != "skill":
        raise ValueError(f"skill {name!r} front-matter missing `kind: skill`")
    return SkillSpec(
        name=name,
        description=meta["description"],
        tool_allowlist=list(meta.get("tool_allowlist", []) or []),
        body=body,
    )


def load_persona(name: str) -> PersonaSpec:
    """Load and parse `instructions/math_conversation/personae/<name>.md`."""
    path = _INSTRUCTIONS_DIR / _DOMAIN / "personae" / f"{name}.md"
    return parse_persona(path.read_text(encoding="utf-8"), name)


def load_skill(name: str) -> SkillSpec:
    """Load and parse `instructions/math_conversation/skills/<name>.md`."""
    path = _INSTRUCTIONS_DIR / _DOMAIN / "skills" / f"{name}.md"
    return parse_skill(path.read_text(encoding="utf-8"), name)
