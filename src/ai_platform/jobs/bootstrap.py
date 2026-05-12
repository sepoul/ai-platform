"""Walk a `DOMAINS` list, register each domain's jobs, and return its
collected routers + job-definition map.

Replaces the per-domain iteration that used to be open-coded in the
API + worker bootstraps before the entrypoints moved into `mathapp.entrypoints`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.domain import BootstrapContext, DomainRegister
from ai_platform.runtime.registry import register_job
from ai_platform.jobs.execution_policy import JobDefinition
from ai_platform.workspace.bootstrap import WorkspaceBootstrap

if TYPE_CHECKING:
    from fastapi import APIRouter


@dataclass
class DomainsBootstrap:
    job_definitions: dict[str, JobDefinition] = field(default_factory=dict)
    routers: list["APIRouter"] = field(default_factory=list)
    artifact_types: list[type[BaseArtifact]] = field(default_factory=list)
    # artifact_type discriminator -> owning domain name. Populated during
    # `register_domains` from each domain's declared `artifact_types`.
    artifact_owners: dict[str, str] = field(default_factory=dict)


def register_domains(
    domains: Iterable[DomainRegister],
    ws: WorkspaceBootstrap,
) -> DomainsBootstrap:
    """Build the `BootstrapContext` from `ws`, call each domain's
    `register()`, and aggregate the results.

    Side effects:
      - each `JobDefinition` is registered on the platform's global
        `_job_definitions` map so router factories can discover it
      - each domain's artifact types are registered on the shared
        `ArtifactService`, which is what the platform artifacts router
        hydrates against
    """
    ctx = BootstrapContext(
        platform_client=ws.platform_client,
        backend=ws.backend,
        artifact_service=ws.artifact_service,
        root_dir=ws.root_dir,
    )

    out = DomainsBootstrap()
    for domain_register in domains:
        domain = domain_register(ctx)
        for job_def in domain.job_definitions:
            register_job(job_def)
            out.job_definitions[job_def.name] = job_def
        out.routers.extend(domain.routers)
        for artifact_cls in domain.artifact_types:
            ws.artifact_service.register(artifact_cls)
            out.artifact_types.append(artifact_cls)
            artifact_type = artifact_cls.model_fields["artifact_type"].default
            if artifact_type is not None:
                out.artifact_owners[artifact_type] = domain.name
    return out
