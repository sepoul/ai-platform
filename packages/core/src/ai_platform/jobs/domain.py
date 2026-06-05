"""Domain self-registration.

A domain package owns its workspace client, job definitions, and any
domain-specific routers. The composition root passes a
`BootstrapContext` to each registered domain's `register()` and the
domain returns a `Domain` describing what to mount.

This keeps the API and worker bootstraps free of per-domain imports —
adding a second domain is a one-line change to the static `DOMAINS`
list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, TYPE_CHECKING

from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.jobs.execution_policy import JobControl, JobExecution
from ai_platform.workspace.client import PlatformClient

if TYPE_CHECKING:
    from fastapi import APIRouter


@dataclass
class BootstrapContext:
    """What every domain's `register_*()` receives at startup.

    Carries enough information for the domain to build its workspace
    client without knowing where the bootstrap was invoked from.
    """

    platform_client: PlatformClient
    backend: str                      # "local" or "b2"
    artifact_service: ArtifactService  # shared platform service; domains contribute types
    root_dir: Optional[str] = None    # only meaningful when backend == "local"


@dataclass
class ControlDomain:
    """What a domain returns from `register_control()` — the API-facing plane.

    `job_controls` carry only schemas (no graph engine); `routers` is the
    domain's optional API surface; `artifact_types` are the `BaseArtifact`
    subclasses it produces (the platform aggregates them to type the
    artifact viewer). Building this must not import the execution engine,
    so the API process stays engine-free.

    `runtime_selector`, `code_entrypoint`, and `control_entrypoint`
    are how the domain identifies itself in the JobDefinition catalog.
    `register_control_domains` uses them to auto-deploy this domain's
    job controls into the catalog at API boot, so the catalog mirrors
    what's in code without requiring a separate bundle-deploy step for
    the platform's own domains. A friend's domain provides the same
    shape; its deploy just hits the same code path with different
    values.

    `code_entrypoint` points at the *execution-plane* register
    callable (the worker imports it). `control_entrypoint` points at
    *this* register callable (the control-plane one); the API imports
    it on boot via catalog-driven discovery so the
    `composition_root._DOMAINS` hardcode can go away.
    """

    name: str
    job_controls: list[JobControl]
    routers: list["APIRouter"] = field(default_factory=list)
    artifact_types: list[type[BaseArtifact]] = field(default_factory=list)
    runtime_selector: str = "default"
    code_entrypoint: str = ""
    control_entrypoint: str = ""


@dataclass
class ExecutionDomain:
    """What a domain returns from `register_execution()` — the worker plane.

    `job_executions` carry the graph engine. `artifact_types` are repeated
    here (not a control-only concern) because the worker's artifact service
    must know them to (de)serialize artifacts it mints/reads at run time.
    """

    name: str
    job_executions: list[JobExecution]
    artifact_types: list[type[BaseArtifact]] = field(default_factory=list)


ControlRegister = Callable[[BootstrapContext], ControlDomain]
ExecutionRegister = Callable[[BootstrapContext], ExecutionDomain]
