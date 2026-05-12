"""Platform workflows router — exposes registered job definitions as graph specs.

Param specs (submit + resume) are derived from the typed pydantic models
(`submit_input_type`, `gate.review_type`) via their JSON schemas — those
models are the single source of truth.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ai_platform.api.pydantic_fields import params_from_model
from ai_platform.runtime.registry import get_job_definitions
from ai_platform.api.schemas.workflows import (
    EdgeResponse,
    GateSpec,
    StageResponse,
    WorkflowListItem,
    WorkflowListResponse,
    WorkflowSpecResponse,
)
from ai_platform.jobs.execution_policy import JobDefinition

router = APIRouter()


@router.get("/workflows", response_model=WorkflowListResponse)
def list_workflows(
    jobs: dict[str, JobDefinition] = Depends(get_job_definitions),
):
    return WorkflowListResponse(
        workflows=[
            WorkflowListItem(job_type=name, label=job_def.graph_ref)
            for name, job_def in jobs.items()
        ]
    )


@router.get("/workflows/{job_type}", response_model=WorkflowSpecResponse)
def get_workflow_spec(
    job_type: str,
    jobs: dict[str, JobDefinition] = Depends(get_job_definitions),
):
    job_def = jobs.get(job_type)
    if job_def is None:
        raise HTTPException(status_code=404, detail=f"Unknown job type: {job_type}")

    stages = []
    for name, node_cls in job_def.node_registry.items():
        gate = job_def.policy.gate_for(name)
        stages.append(StageResponse(
            id=name,
            label=getattr(node_cls, "stage_label", name),
            description=getattr(node_cls, "stage_description", None),
            is_human_step=gate is not None,
            resume_params=params_from_model(gate.review_type, skip_fields=("job_type",)) if gate else [],
        ))

    gates = [
        GateSpec(
            node_name=g.node_name,
            review_type=g.review_type.__name__,
            params=params_from_model(g.review_type, skip_fields=("job_type",)),
        )
        for g in job_def.policy.gates
    ]

    return WorkflowSpecResponse(
        job_type=job_type,
        submit_params=params_from_model(job_def.submit_input_type, skip_fields=("job_type",)),
        stages=stages,
        edges=[
            EdgeResponse(source=e.source, target=e.target, label=e.label)
            for e in job_def.edges
        ],
        gates=gates,
    )
