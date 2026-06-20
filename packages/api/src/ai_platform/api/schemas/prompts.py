"""API schemas for the prompt registry CRUD endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class PromptResponse(BaseModel):
    id: str
    name: str
    domain: str
    description: str
    instructions: str
    version: str
    created_at: datetime
    updated_at: datetime


class PromptUpdateRequest(BaseModel):
    instructions: Optional[str] = None


class PromptCreateRequest(BaseModel):
    """Body for `POST /prompts` — a domain deploying one of its prompts.
    Get-or-create / idempotent on `name` (mirrors `POST /artifact-types`):
    an existing prompt is left untouched; use `PUT` to change instructions."""
    name: str                       # e.g. "math_qa.answer"
    domain: str                     # grouping key, e.g. "math_qa"
    description: str
    instructions: str
    kind: str = "prompt"            # "prompt" | "persona" | "skill"
    version: str = "0.1.0"


class PromptListResponse(BaseModel):
    prompts: List[PromptResponse]
    total: int


class PromptExecutionSummary(BaseModel):
    id: str
    prompt_name: str
    prompt_version: str
    executed_at: datetime
    model_name: Optional[str] = None


class PromptExecutionResponse(BaseModel):
    id: str
    prompt_name: str
    prompt_version: str
    input_data: Dict[str, Any]
    executed_at: datetime
    model_name: Optional[str] = None
    output_type: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


class PromptExecutionListResponse(BaseModel):
    executions: List[PromptExecutionSummary]
    total: int
