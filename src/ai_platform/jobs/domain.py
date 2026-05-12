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
from ai_platform.jobs.execution_policy import JobDefinition
from ai_platform.workspace.client import PlatformClient

if TYPE_CHECKING:
    from fastapi import APIRouter


@dataclass
class BootstrapContext:
    """What every domain's `register()` receives at startup.

    Carries enough information for the domain to build its workspace
    client without knowing where the bootstrap was invoked from.
    """

    platform_client: PlatformClient
    backend: str                      # "local" or "b2"
    artifact_service: ArtifactService  # shared platform service; domains contribute types via `Domain.artifact_types`
    root_dir: Optional[str] = None    # only meaningful when backend == "local"


@dataclass
class Domain:
    """What a domain returns from `register()`.

    `routers` is empty for worker bootstraps that only care about jobs.
    `artifact_types` is the set of `BaseArtifact` subclasses this domain
    produces — the platform aggregates them to type the artifact viewer
    endpoint.
    Domains are responsible for any side-effecting dependency wiring
    (FastAPI Depends singletons, etc.) inside their `register()` body
    before returning the `Domain` value.
    """

    name: str
    job_definitions: list[JobDefinition]
    routers: list["APIRouter"] = field(default_factory=list)
    artifact_types: list[type[BaseArtifact]] = field(default_factory=list)


DomainRegister = Callable[[BootstrapContext], Domain]
