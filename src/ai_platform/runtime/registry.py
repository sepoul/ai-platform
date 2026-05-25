"""Process-level DI singletons for the platform.

Lives outside `ai_platform.api` so that `ai_platform.jobs` (and any other
non-API consumer) can register or read from the registry without
inverting the layering. Before this module existed, `jobs.bootstrap`
had to import from `api.dependencies`, creating a `jobs → api` edge
inside the platform.

The composition root (e.g. `mathapp.entrypoints.api`) calls
`init_platform()` once at startup. Routers consume the singletons via
FastAPI `Depends(get_*)`. Tests bypass `init_platform` and override
the dependencies directly via `app.dependency_overrides[get_*]`.
"""
from __future__ import annotations

from typing import Optional

from ai_platform.compute.base import ComputeBackend
from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.jobs.execution_policy import JobControl
from ai_platform.jobs.graph_execution import GraphJobExecutor
from ai_platform.workspace.client import PlatformClient


_platform_client: Optional[PlatformClient] = None
_executor: Optional[GraphJobExecutor] = None
_compute: Optional[ComputeBackend] = None
_artifact_service: Optional[ArtifactService] = None
# Control-plane only: the API serves submission/result/status from these.
# Execution objects never enter the API process (see control/execution split).
_job_controls: dict[str, JobControl] = {}


def init_platform(
    platform_client: PlatformClient,
    executor: GraphJobExecutor,
    compute: ComputeBackend,
    artifact_service: ArtifactService,
) -> None:
    global _platform_client, _executor, _compute, _artifact_service
    _platform_client = platform_client
    _executor = executor
    _compute = compute
    _artifact_service = artifact_service


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
