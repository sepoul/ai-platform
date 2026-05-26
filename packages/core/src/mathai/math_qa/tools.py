"""Agent tools for the math_qa workflow.

`validate_latex` round-trips content through the math-ui Next.js
endpoint (`POST /api/tools/validate-latex`), where KaTeX runs with
`throwOnError: true`. The tool returns a structured pass/fail so the
agent can self-correct on retry.

The default `mode="document"` is what the math_qa agent wants: it
accepts a full markdown answer with `\\(...\\)` and `\\[...\\]`
delimiters, splits it on the server, and validates each math segment
independently. Prose is ignored. `inline` / `block` are still
available when the caller has a bare math expression.

The endpoint URL is read from `UI_TOOL_API_URL` (default
`http://localhost:3000`) so dev / Docker / Spaces deployments can
point at different hosts.
"""
from __future__ import annotations

import os
from typing import Literal, Optional

import httpx
from pydantic import BaseModel


_DEFAULT_UI_URL = "http://localhost:3000"
_TIMEOUT_SECONDS = 10.0


class LatexValidationResult(BaseModel):
    valid: bool
    error: Optional[str] = None
    # Populated when `mode="document"` and a specific math segment
    # failed — lets the agent locate the issue without re-scanning.
    segment: Optional[str] = None
    segment_index: Optional[int] = None


def _ui_url() -> str:
    return os.getenv("UI_TOOL_API_URL", _DEFAULT_UI_URL).rstrip("/")


async def validate_latex(
    latex: str,
    mode: Literal["inline", "block", "document"] = "document",
) -> LatexValidationResult:
    """Validate KaTeX-compilable content via the UI server.

    `mode="document"` (default): `latex` is a full markdown answer
    with `\\(...\\)` / `\\[...\\]` math delimiters. Each math segment
    is validated independently; prose is ignored.

    `mode="inline"` / `"block"`: `latex` is a bare math expression.

    Returns `{valid: true}` on success, otherwise `{valid: false,
    error, segment?, segment_index?}` — the agent should read `error`
    and (when set) `segment` to locate the issue and correct.
    """
    url = f"{_ui_url()}/api/tools/validate-latex"
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json={"latex": latex, "mode": mode})
        response.raise_for_status()
        return LatexValidationResult.model_validate(response.json())


class FigureValidationResult(BaseModel):
    valid: bool
    error: Optional[str] = None
    # `path` is a JSON-pointer-ish locator like "relations[0].type"
    # so the agent can tell the model exactly where to fix.
    path: Optional[str] = None


async def validate_figure(spec: dict) -> FigureValidationResult:
    """Validate a semantic figure spec via the UI server's
    `/api/tools/validate-figure` endpoint.

    The check is structural: known template, known object types,
    known relation types, well-formed labels. Returns `{valid: true}`
    on success, otherwise `{valid: false, error, path?}`.

    `spec` is the full JSON object — `{template, labels, objects,
    relations, notes, ...}`. Same shape the renderer in math-ui
    consumes; same shape this prompt's few-shot examples use.
    """
    url = f"{_ui_url()}/api/tools/validate-figure"
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json={"spec": spec})
        response.raise_for_status()
        return FigureValidationResult.model_validate(response.json())
