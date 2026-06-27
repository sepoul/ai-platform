"""Platform workflows router — serves the static workflow descriptors.

The descriptors are generated offline by an admin command running in an
engine context (`ai_platform.entrypoints.gen_workflows`) and parked in the
blob store as a single `workflows.json`. This router only reads + serves
them, so the API never imports `pydantic_graph`. The endpoints are
**optional**: if the blob hasn't been generated yet, `/workflows` is empty
and `/workflows/{job_type}` 404s.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ai_platform.jobs.workflow_schemas import (
    WorkflowListItem,
    WorkflowListResponse,
    WorkflowSpecResponse,
)
from ai_platform.jobs.workflow_descriptor import WORKFLOWS_BLOB
from ai_platform.runtime.registry import get_platform_client
from ai_platform.workspace.client import PlatformClient
from ai_platform.workspace.storage.blobs.base import PutFilePayload
from ai_platform.workspace.storage.exceptions import ObjectNotFound

router = APIRouter()


class WorkflowsPushRequest(BaseModel):
    """A map of `{job_type: descriptor}` to merge into the workflows blob."""
    workflows: dict[str, WorkflowSpecResponse]


class WorkflowsPushResponse(BaseModel):
    job_types: list[str]  # every job type in the blob after the merge


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


@router.post("/workflows", response_model=WorkflowsPushResponse)
def push_workflows(
    body: WorkflowsPushRequest,
    client: PlatformClient = Depends(get_platform_client),
):
    """Merge-upsert workflow descriptors into the blob the GET endpoints serve.

    This is the deploy-flow seam for #56: a domain-side `export-workflows`
    (engine context) emits the descriptors as JSON, and the standalone CLI
    POSTs them here. **Merge**, not replace — posted job types are upserted
    and existing ones preserved — so each runtime can push only the job
    types it can see (`default`, `crewai`, …) and they accumulate into the
    single blob. Idempotent: re-pushing the same descriptors is a no-op.
    """
    descriptors = _load_descriptors(client)
    for job_type, spec in body.workflows.items():
        # Key by the spec's own job_type so the blob is self-consistent with
        # what `GET /workflows/{job_type}` looks up.
        descriptors[spec.job_type] = spec.model_dump(mode="json")

    payload = json.dumps(descriptors, indent=2, sort_keys=True).encode("utf-8")
    client.file_repo.put_canonical_file(
        PutFilePayload(
            logical_name=WORKFLOWS_BLOB,
            bytes_data=payload,
            content_type="application/json",
        )
    )
    return WorkflowsPushResponse(job_types=sorted(descriptors))


@router.get("/workflows/{job_type}", response_model=WorkflowSpecResponse)
def get_workflow_spec(
    job_type: str,
    client: PlatformClient = Depends(get_platform_client),
):
    descriptor = _load_descriptors(client).get(job_type)
    if descriptor is None:
        raise HTTPException(status_code=404, detail=f"Unknown job type: {job_type}")
    return WorkflowSpecResponse.model_validate(descriptor)
