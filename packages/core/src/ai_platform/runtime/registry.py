"""Process-level DI singletons for the platform.

Lives outside `ai_platform.api` so that `ai_platform.jobs` (and any other
non-API consumer) can register or read from the registry without
inverting the layering. Before this module existed, `jobs.bootstrap`
had to import from `api.dependencies`, creating a `jobs → api` edge
inside the platform.

The composition root (e.g. `ai_platform.entrypoints.api`) calls
`init_platform()` once at startup. Routers consume the singletons via
FastAPI `Depends(get_*)`. Tests bypass `init_platform` and override
the dependencies directly via `app.dependency_overrides[get_*]`.
"""
from __future__ import annotations

from typing import Optional

from ai_platform.compute.base import ComputeBackend
from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.jobs.artifact_type_service import ArtifactTypeService
from ai_platform.jobs.code_package_service import CodePackageService
from ai_platform.jobs.execution_policy import JobControl
from ai_platform.jobs.media_service import MediaService
from ai_platform.jobs.graph_execution import GraphJobExecutor
from ai_platform.jobs.job_definition_service import JobDefinitionService
from ai_platform.workspace.client import PlatformClient


_platform_client: Optional[PlatformClient] = None
_executor: Optional[GraphJobExecutor] = None
_compute: Optional[ComputeBackend] = None
_artifact_service: Optional[ArtifactService] = None
_job_definition_service: Optional[JobDefinitionService] = None
_artifact_type_service: Optional[ArtifactTypeService] = None
_code_package_service: Optional[CodePackageService] = None
_media_service: Optional[MediaService] = None
# Control-plane only: the API serves submission/result/status from these.
# Execution objects never enter the API process (see control/execution split).
_job_controls: dict[str, JobControl] = {}


def init_platform(
    platform_client: PlatformClient,
    executor: GraphJobExecutor,
    compute: ComputeBackend,
    artifact_service: ArtifactService,
    job_definition_service: JobDefinitionService | None = None,
    artifact_type_service: ArtifactTypeService | None = None,
    code_package_service: CodePackageService | None = None,
    media_service: MediaService | None = None,
) -> None:
    global _platform_client, _executor, _compute, _artifact_service
    global _job_definition_service, _artifact_type_service, _code_package_service
    global _media_service
    _platform_client = platform_client
    _executor = executor
    _compute = compute
    _artifact_service = artifact_service
    _job_definition_service = job_definition_service
    _artifact_type_service = artifact_type_service
    _code_package_service = code_package_service
    _media_service = media_service


def register_job_control(control: JobControl) -> None:
    _job_controls[control.name] = control


def get_platform_client() -> PlatformClient:
    if _platform_client is None:
        raise RuntimeError("Platform not initialized — call init_platform() first")
    return _platform_client


def get_executor() -> GraphJobExecutor:
    if _executor is None:
        raise RuntimeError("Platform not initialized — call init_platform() first")
    return _executor


def get_compute() -> ComputeBackend:
    if _compute is None:
        raise RuntimeError("Platform not initialized — call init_platform() first")
    return _compute


def get_artifact_service() -> ArtifactService:
    if _artifact_service is None:
        raise RuntimeError("Platform not initialized — call init_platform() first")
    return _artifact_service


def get_job_controls() -> dict[str, JobControl]:
    return _job_controls


def get_job_definition_service() -> JobDefinitionService:
    if _job_definition_service is None:
        raise RuntimeError(
            "JobDefinitionService not initialized — pass it to init_platform()"
        )
    return _job_definition_service


def get_artifact_type_service() -> ArtifactTypeService:
    if _artifact_type_service is None:
        raise RuntimeError(
            "ArtifactTypeService not initialized — pass it to init_platform()"
        )
    return _artifact_type_service


def get_code_package_service() -> CodePackageService:
    if _code_package_service is None:
        raise RuntimeError(
            "CodePackageService not initialized — pass it to init_platform()"
        )
    return _code_package_service


def get_media_service() -> MediaService:
    if _media_service is None:
        raise RuntimeError(
            "MediaService not initialized — pass it to init_platform()"
        )
    return _media_service
