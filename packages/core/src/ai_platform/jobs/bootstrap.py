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

import logging

from ai_platform.bundle import build_record
from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.domain import (
    BootstrapContext,
    ControlRegister,
    ExecutionRegister,
)
from ai_platform.runtime.registry import register_job_control
from ai_platform.jobs.execution_policy import JobControl, JobExecution
from ai_platform.workspace.bootstrap import WorkspaceBootstrap


_logger = logging.getLogger(__name__)

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

    Side effects:
    1. Each JobControl is registered on the platform's global control
       registry so router factories can discover it.
    2. Each ControlDomain is auto-deployed to the JobDefinition catalog
       via `ws.job_definition_service.deploy(...)` — idempotent upsert.
       After boot the catalog mirrors what's in code; a friend's
       additional `POST /job-definitions` deploy is additive.

       The auto-deploy is best-effort: if the JobDefinitionService is
       unavailable (older WorkspaceBootstrap, test that bypasses
       storage, …) the registration still completes. Routing today
       still consumes the in-memory registry, so a deploy-time
       failure doesn't break the API.
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

        _auto_deploy_to_catalog(domain, ws)
    return out


def _auto_deploy_to_catalog(domain, ws: WorkspaceBootstrap) -> None:
    """Upsert each of `domain`'s JobControls into the JobDefinition catalog.

    Failures are logged + swallowed: the platform's in-memory routing
    still works without the catalog, and we don't want a bad DB
    connection to block API boot. Bundle deploy from a friend's repo
    surfaces errors through the API's HTTP response — that's the
    enforced path; this one is convenience.
    """
    service = getattr(ws, "job_definition_service", None)
    if service is None:
        return  # Older bootstrap shape; nothing to do.
    if not domain.code_entrypoint:
        # Domain didn't self-describe — skip rather than guess a wrong
        # entrypoint into the catalog.
        return
    for control in domain.job_controls:
        try:
            record = build_record(
                control,
                runtime=domain.runtime_selector,
                code_entrypoint=domain.code_entrypoint,
                artifact_types=tuple(domain.artifact_types),
            )
            service.deploy(record)
        except Exception as exc:  # noqa: BLE001 — best-effort
            _logger.warning(
                "Auto-deploy to JobDefinition catalog failed for %s: %s",
                control.name,
                exc,
            )


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
