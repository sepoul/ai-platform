"""Platform prompts router — CRUD over the prompt registry on PlatformClient."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ai_platform.runtime.registry import get_platform_client
from ai_platform.api.schemas.prompts import (
    PromptExecutionListResponse,
    PromptExecutionResponse,
    PromptExecutionSummary,
    PromptListResponse,
    PromptResponse,
    PromptUpdateRequest,
)
from ai_platform.workspace.client import PlatformClient
from ai_platform.workspace.prompt_registry import PromptRegistry
from ai_platform.workspace.storage.exceptions import ObjectNotFound

router = APIRouter()


def _get_prompt_service(client: PlatformClient = Depends(get_platform_client)) -> PromptRegistry:
    if client.prompt_registry is None:
        raise HTTPException(status_code=503, detail="Prompt registry not configured")
    return client.prompt_registry


def _to_response(prompt) -> PromptResponse:
    return PromptResponse(**prompt.model_dump())


@router.get("/prompts", response_model=PromptListResponse)
def list_prompts(
    domain: Optional[str] = None,
    svc: PromptRegistry = Depends(_get_prompt_service),
):
    prompts = svc.list_prompts(domain=domain)
    return PromptListResponse(
        prompts=[_to_response(p) for p in prompts],
        total=len(prompts),
    )


@router.get("/prompts/{name:path}", response_model=PromptResponse)
def get_prompt(
    name: str,
    svc: PromptRegistry = Depends(_get_prompt_service),
):
    try:
        prompt = svc.get_prompt(name)
    except ObjectNotFound:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")
    return _to_response(prompt)


@router.put("/prompts/{name:path}", response_model=PromptResponse)
def update_prompt(
    name: str,
    body: PromptUpdateRequest,
    svc: PromptRegistry = Depends(_get_prompt_service),
):
    try:
        existing = svc.get_prompt(name)
    except ObjectNotFound:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")

    if body.instructions is not None:
        return _to_response(svc.update_instructions(name, body.instructions))
    return _to_response(existing)


@router.get("/prompt-executions", response_model=PromptExecutionListResponse)
def list_executions(
    prompt_name: Optional[str] = None,
    svc: PromptRegistry = Depends(_get_prompt_service),
):
    executions = svc.list_executions()
    if prompt_name:
        executions = [e for e in executions if e.prompt_name == prompt_name]
    return PromptExecutionListResponse(
        executions=[
            PromptExecutionSummary(**e.model_dump(include={"id", "prompt_name", "prompt_version", "executed_at", "model_name"}))
            for e in executions
        ],
        total=len(executions),
    )


@router.get("/prompt-executions/{execution_id}", response_model=PromptExecutionResponse)
def get_execution(
    execution_id: str,
    svc: PromptRegistry = Depends(_get_prompt_service),
):
    for e in svc.list_executions():
        if e.id == execution_id:
            return PromptExecutionResponse(**e.model_dump())
    raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")
