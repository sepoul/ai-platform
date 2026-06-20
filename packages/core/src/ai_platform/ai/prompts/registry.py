"""Generic prompt-loading helpers.

The platform does **not** own domain prompts. Domains keep their own
instruction files and declare them via the bundle's `[prompts]` section,
deployed over HTTP by `aiplatform deploy-prompts` (the prompt counterpart
to `declare-artifacts`). This module only does the generic, domain-agnostic
work: split YAML front-matter and build deployable `Prompt` entries from a
domain-provided instructions directory.

`parse_frontmatter` is also imported by domains (e.g.
`mathai.math_conversation.registry`) to interpret persona/skill front-matter
into their own typed specs — the *interpretation* is a domain concern; the
*split* is generic and lives here.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import yaml

from ai_platform.ai.prompts.models import Prompt


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
    the generic loader behind `aiplatform deploy-prompts`. The domain owns
    the files; this never hardcodes a platform path.

    Naming:
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
