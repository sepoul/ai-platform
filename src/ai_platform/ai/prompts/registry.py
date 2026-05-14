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
from typing import List

from ai_platform.ai.prompts.models import Prompt

# Resolve the instructions root relative to the repo root.

_INSTRUCTIONS_DIR = Path(__file__).resolve().parents[4] / "instructions"


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
]
