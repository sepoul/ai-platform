"""Walk a domain register list and aggregate the results — split by plane.

`register_control_domains` (API process) collects JobControls + routers +
artifact types and populates the platform's control registry.
`register_execution_domains` (worker process) collects JobExecutions and
registers artifact types so the worker can (de)serialize what it mints.

The two never run in the same process: the API imports only control
modules (no engine), workers import only their runtime's execution modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.domain import (
    BootstrapContext,
    ControlRegister,
    ExecutionRegister,
)
from ai_platform.runtime.registry import register_job_control
from ai_platform.jobs.execution_policy import JobControl, JobExecution
from ai_platform.workspace.bootstrap import WorkspaceBootstrap

if TYPE_CHECKING:
    from fastapi import APIRouter


def _ctx(ws: WorkspaceBootstrap) -> BootstrapContext:
    return BootstrapContext(
        platform_client=ws.platform_client,
        backend=ws.backend,
        artifact_service=ws.artifact_service,
        root_dir=ws.root_dir,
    )


@dataclass
class ControlBootstrap:
    job_controls: dict[str, JobControl] = field(default_factory=dict)
    routers: list["APIRouter"] = field(default_factory=list)
    artifact_types: list[type[BaseArtifact]] = field(default_factory=list)
    # artifact_type discriminator -> owning domain name.
    artifact_owners: dict[str, str] = field(default_factory=dict)


@dataclass
class ExecutionBootstrap:
    job_executions: dict[str, JobExecution] = field(default_factory=dict)


def _register_artifact_types(ws: WorkspaceBootstrap, types: list[type[BaseArtifact]]) -> None:
    for artifact_cls in types:
        ws.artifact_service.register(artifact_cls)


def register_control_domains(
    domains: Iterable[ControlRegister],
    ws: WorkspaceBootstrap,
) -> ControlBootstrap:
    """Call each domain's `register_control()` and aggregate (API process).

    Side effect: each JobControl is registered on the platform's global
    control registry so router factories can discover it.
    """
    ctx = _ctx(ws)
    out = ControlBootstrap()
    for register in domains:
        domain = register(ctx)
        for control in domain.job_controls:
            register_job_control(control)
            out.job_controls[control.name] = control
        out.routers.extend(domain.routers)
        _register_artifact_types(ws, domain.artifact_types)
        for artifact_cls in domain.artifact_types:
            out.artifact_types.append(artifact_cls)
            artifact_type = artifact_cls.model_fields["artifact_type"].default
            if artifact_type is not None:
                out.artifact_owners[artifact_type] = domain.name
    return out


def register_execution_domains(
    domains: Iterable[ExecutionRegister],
    ws: WorkspaceBootstrap,
) -> ExecutionBootstrap:
    """Call each domain's `register_execution()` and aggregate (worker process).

    Registers artifact types on the shared service so the worker can
    (de)serialize artifacts it mints/reads while running the graph.
    """
    ctx = _ctx(ws)
    out = ExecutionBootstrap()
    for register in domains:
        domain = register(ctx)
        for execution in domain.job_executions:
            out.job_executions[execution.name] = execution
        _register_artifact_types(ws, domain.artifact_types)
    return out
