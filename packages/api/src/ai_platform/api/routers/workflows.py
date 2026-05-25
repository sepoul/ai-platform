"""Platform workflows router — serves the static workflow descriptors.

The descriptors are generated offline by an admin command running in an
engine context (`mathapp.entrypoints.gen_workflows`) and parked in the
blob store as a single `workflows.json`. This router only reads + serves
them, so the API never imports `pydantic_graph`. The endpoints are
**optional**: if the blob hasn't been generated yet, `/workflows` is empty
and `/workflows/{job_type}` 404s.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from ai_platform.jobs.workflow_schemas import (
    WorkflowListItem,
    WorkflowListResponse,
    WorkflowSpecResponse,
)
from ai_platform.jobs.workflow_descriptor import WORKFLOWS_BLOB
from ai_platform.runtime.registry import get_platform_client
from ai_platform.workspace.client import PlatformClient
from ai_platform.workspace.storage.exceptions import ObjectNotFound

router = APIRouter()


def _load_descriptors(client: PlatformClient) -> dict[str, dict]:
    """`{job_type: descriptor}` from the blob store, or empty if ungenerated."""
    try:
        raw = client.file_repo.get_canonical_file_bytes(WORKFLOWS_BLOB)
    except ObjectNotFound:
        return {}
    return json.loads(raw)


@router.get("/workflows", response_model=WorkflowListResponse)
def list_workflows(client: PlatformClient = Depends(get_platform_client)):
    descriptors = _load_descriptors(client)
    return WorkflowListResponse(
        workflows=[
            WorkflowListItem(job_type=job_type, label=d.get("label", job_type))
            for job_type, d in descriptors.items()
        ]
    )


@router.get("/workflows/{job_type}", response_model=WorkflowSpecResponse)
def get_workflow_spec(
    job_type: str,
    client: PlatformClient = Depends(get_platform_client),
):
    descriptor = _load_descriptors(client).get(job_type)
    if descriptor is None:
        raise HTTPException(status_code=404, detail=f"Unknown job type: {job_type}")
    return WorkflowSpecResponse.model_validate(descriptor)
