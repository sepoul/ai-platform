"""Single source of truth for backend selection.

Reads `BACKEND` / `LOCAL_DATA_DIR` / `B2_*` env vars once via
`make_backend()` and returns the value object every entry point (API,
worker, scripts) needs: the platform client, a job repo wired into a
graph executor, and the local root dir when applicable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.jobs.artifact_type_service import ArtifactTypeService
from ai_platform.jobs.code_package_service import CodePackageService
from ai_platform.jobs.graph_execution import GraphJobExecutor
from ai_platform.jobs.job_definition_service import JobDefinitionService
from ai_platform.jobs.media_service import MediaService
from ai_platform.workspace.client import PlatformClient
from ai_platform.workspace.storage.backends import LocalBackend, make_backend


@dataclass
class WorkspaceBootstrap:
    """Everything an entry point needs after wiring storage."""

    backend: str                      # "local" or "b2"
    platform_client: PlatformClient
    executor: GraphJobExecutor
    artifact_service: ArtifactService  # shared across domains; types added by register_*_domains
    job_definition_service: JobDefinitionService  # catalog of deployed JobDefinitions
    artifact_type_service: ArtifactTypeService    # catalog of deployed BaseArtifact types
    code_package_service: CodePackageService      # installable wheels + their metadata
    media_service: MediaService                   # user-uploaded bytes -> storage_ref (PR-1)
    root_dir: Optional[str]           # only meaningful when backend == "local"


def bootstrap_workspace() -> WorkspaceBootstrap:
    backend = make_backend()
    return WorkspaceBootstrap(
        backend=backend.name,
        platform_client=PlatformClient.from_backend(backend),
        executor=GraphJobExecutor(backend.job_repo),
        artifact_service=ArtifactService(backend.artifact_repo, registry={}),
        job_definition_service=JobDefinitionService(backend.job_definition_repo),
        artifact_type_service=ArtifactTypeService(backend.artifact_type_repo),
        code_package_service=CodePackageService(
            backend.code_package_repo, backend.file_repo
        ),
        media_service=MediaService(backend.file_repo),
        root_dir=backend.root_dir if isinstance(backend, LocalBackend) else None,
    )
