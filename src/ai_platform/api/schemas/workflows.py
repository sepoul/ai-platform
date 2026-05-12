"""Schemas for the workflows (graph specs) endpoint."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class ParamSpec(BaseModel):
    name: str
    type: str
    required: bool = True
    description: str = ""


class StageResponse(BaseModel):
    id: str
    label: str
    description: Optional[str] = None
    is_human_step: bool = False
    resume_params: List[ParamSpec] = []


class EdgeResponse(BaseModel):
    source: str
    target: str
    label: Optional[str] = None


class GateSpec(BaseModel):
    """Execution-policy gate — declares that after `node_name` runs,
    a human review of `review_type` must be submitted before the
    workflow continues.
    """
    node_name: str
    review_type: str            # pydantic model class name (e.g. "UserComment")
    params: List[ParamSpec] = []


class WorkflowSpecResponse(BaseModel):
    job_type: str
    submit_params: List[ParamSpec] = []
    stages: List[StageResponse]
    edges: List[EdgeResponse]
    gates: List[GateSpec] = []  # flattened ExecutionPolicy


class WorkflowListItem(BaseModel):
    """Lightweight registry entry — drives the platform-level workflow index."""
    job_type: str
    label: str


class WorkflowListResponse(BaseModel):
    workflows: List[WorkflowListItem]
