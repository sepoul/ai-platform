"""Build the static workflow descriptor the API serves.

A descriptor is the API-facing projection of a job's graph — stages,
edges, gates, and submit params, i.e. the `WorkflowSpecResponse` shape.
It is generated offline by an admin command running in an engine context
(`mathapp.entrypoints.gen_workflows`) and parked in the blob store, so the
API never introspects `pydantic_graph` at request time. The topology is
static per deploy; regenerate after graph changes.

This module is import-light (pydantic only, no FastAPI), so the admin
command can import it without pulling the web framework.
"""
from __future__ import annotations

from ai_platform.api.pydantic_fields import params_from_model
from ai_platform.api.schemas.workflows import (
    EdgeResponse,
    GateSpec,
    StageResponse,
    WorkflowSpecResponse,
)
from ai_platform.jobs.execution_policy import JobControl, JobExecution

# logical_name of the single blob holding {job_type: descriptor}.
WORKFLOWS_BLOB = "workflows.json"


def build_workflow_descriptor(
    control: JobControl, execution: JobExecution
) -> WorkflowSpecResponse:
    """Project a job's two planes into the static workflow descriptor.

    Needs both: schemas come from the control plane (submit/review params),
    topology from the execution plane (node_registry, policy, edges). That's
    why this runs at generation time in an engine context, never in the API.
    """
    policy = execution.policy
    stages = [
        StageResponse(
            id=name,
            label=getattr(node_cls, "stage_label", name),
            description=getattr(node_cls, "stage_description", None),
            is_human_step=policy.gate_for(name) is not None,
            resume_params=(
                params_from_model(gate.review_type, skip_fields=("job_type",))
                if (gate := policy.gate_for(name))
                else []
            ),
        )
        for name, node_cls in execution.node_registry.items()
    ]
    gates = [
        GateSpec(
            node_name=g.node_name,
            review_type=g.review_type.__name__,
            params=params_from_model(g.review_type, skip_fields=("job_type",)),
        )
        for g in policy.gates
    ]
    return WorkflowSpecResponse(
        job_type=control.name,
        label=control.label,
        submit_params=params_from_model(control.submit_input_type, skip_fields=("job_type",)),
        stages=stages,
        edges=[EdgeResponse(source=e.source, target=e.target, label=e.label) for e in execution.edges],
        gates=gates,
    )
