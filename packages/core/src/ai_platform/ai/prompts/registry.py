"""
Prompt definitions registry — v0 of all prompts.

Each entry pairs a Prompt with its instruction text loaded from the
``instructions/`` directory.  Instructions document what the prompt
expects to receive; agents are responsible for augmenting the prompt
with actual data at execution time.

The deploy script reads PROMPT_DEFINITIONS and uses get-or-create
semantics to seed the prompt repository.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import yaml

from ai_platform.ai.prompts.models import Prompt
from ai_platform.utilities.paths import find_ancestor_containing

# Walk up to the dir containing instructions/ (robust to package depth).
_INSTRUCTIONS_DIR = find_ancestor_containing("instructions") / "instructions"


def _load(domain: str, name: str) -> str:
    """Read an instruction file and return its contents."""
    path = _INSTRUCTIONS_DIR / domain / f"{name}.md"
    return path.read_text(encoding="utf-8")


def _prompt(domain: str, name: str, description: str) -> Prompt:
    return Prompt(
        name=f"{domain}.{name}",
        domain=domain,
        description=description,
        instructions=_load(domain, name),
        version="0.1.0",
    )


# ---------------------------------------------------------------------------
# Generic front-matter parsing + persona/skill discovery
#
# The *interpretation* of persona/skill front-matter into typed specs is a
# domain concern and lives in `mathai.math_conversation.registry` — the
# platform never imports a domain. Here we only do the generic work:
# split YAML front-matter and build deployable `Prompt` entries.
# ---------------------------------------------------------------------------

def parse_frontmatter(markdown: str) -> Tuple[dict, str]:
    """Split a Markdown file into (front-matter dict, body).

    Front-matter is a leading YAML block fenced by `---` lines. A file
    without front-matter returns ({}, whole-text).
    """
    text = markdown.lstrip("﻿")
    if not text.startswith("---"):
        return {}, text.strip()
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text.strip()
    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict):
        raise ValueError("Front-matter must be a YAML mapping")
    return meta, parts[2].strip()


_VALID_KINDS = ("prompt", "persona", "skill")


def load_prompts_from_dir(instructions_dir: "Path | str", domain: str) -> List[Prompt]:
    """Build deployable `Prompt`s from a domain's instructions directory —
    the generic, domain-agnostic loader behind `aiplatform deploy-prompts`.
    The domain owns the files; this never hardcodes a platform path.

    Naming mirrors the registry convention:
      - top-level `<name>.md`       -> name `<domain>.<name>`, kind "prompt"
      - nested `<kind>/<name>.md`   -> name `<domain>.<kind>.<name>`, kind=`<kind>`
    Front-matter overrides where present: `name`, `kind`, `description`
    (or `role`), `version`. The whole file (front-matter + body) is stored as
    `instructions` so a `/prompts` round-trip is lossless. `README.md` skipped.
    """
    base = Path(instructions_dir)
    out: List[Prompt] = []
    for path in sorted(base.rglob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8")
        meta, _body = parse_frontmatter(text)
        rel = path.relative_to(base).with_suffix("")
        parts = rel.parts
        if len(parts) == 1:
            kind = str(meta.get("kind") or "prompt")
            name = str(meta.get("name") or f"{domain}.{parts[0]}")
        else:
            kind = str(meta.get("kind") or parts[0])
            name = str(meta.get("name") or f"{domain}.{'.'.join(parts)}")
        if kind not in _VALID_KINDS:
            kind = "prompt"
        out.append(Prompt(
            name=name,
            domain=domain,
            description=str(meta.get("description") or meta.get("role") or rel.name),
            instructions=text,
            kind=kind,  # type: ignore[arg-type]
            version=str(meta.get("version") or "0.1.0"),
        ))
    return out


def discover_kinded(domain: str, subdir: str, kind: str) -> List[Prompt]:
    """Build registry entries for every persona/skill Markdown file under
    `instructions/<domain>/<subdir>/`.

    The full Markdown (front-matter + body) is stored as `instructions`
    so a `/prompts` round-trip preserves the front-matter; the
    description is lifted from the front-matter for the listing.
    """
    base = _INSTRUCTIONS_DIR / domain / subdir
    if not base.is_dir():
        return []
    out: List[Prompt] = []
    for path in sorted(base.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, _ = parse_frontmatter(raw)
        stem = path.stem
        description = meta.get("description") or meta.get("role") or stem
        out.append(Prompt(
            name=f"{domain}.{kind}.{stem}",
            domain=domain,
            description=description,
            instructions=raw,
            kind=kind,  # type: ignore[arg-type]
            version="0.1.0",
        ))
    return out


# ============================================================================
# All v0 prompt definitions
# ============================================================================

PROMPT_DEFINITIONS: List[Prompt] = [
    # --- math_qa (3) ---
    _prompt("math_qa", "answer",
            "Solve a math question with a step-by-step plain-prose explanation."),
    _prompt("math_qa", "latex_render",
            "Convert an answer into KaTeX-validated LaTeX via the validate_latex tool loop."),
    _prompt("math_qa", "figure",
            "Generate a textbook-style figure JSON (Munkres/Lee/Tu) via the validate_figure tool loop."),
    # --- math_conversation personae + skills (discovered from disk) ---
    *discover_kinded("math_conversation", "personae", "persona"),
    *discover_kinded("math_conversation", "skills", "skill"),
]
