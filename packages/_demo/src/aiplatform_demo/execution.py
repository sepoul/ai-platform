"""Demo domain execution plane.

Imports pydantic_graph (the platform graph framework — light dep) but
no LLM stack. The worker imports this lazily after the catalog install
pass.
"""
from __future__ import annotations

from uuid import UUID

from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.jobs.domain import BootstrapContext, ExecutionDomain
from ai_platform.jobs.execution_policy import (
    ExecutionPolicy,
    JobExecution,
    PersistencePolicy,
)
from ai_platform.runtime.worker_log import NullLogger, WorkerLogger
from ai_platform.workspace.client import PlatformClient
from aiplatform_demo.artifacts import DEMO_ARTIFACTS, DemoEchoArtifact
from aiplatform_demo.state import DemoState
from aiplatform_demo.workflow import (
    DemoWorkflowDependencies,
    _extract_demo_result,
    demo_graph,
    demo_node_registry,
)


# No human gates — the demo runs to completion every time.
demo_policy = ExecutionPolicy(gates=[])


def build_demo_execution(
    artifact_api: ArtifactService,
    platform_client: PlatformClient,
) -> JobExecution:
    def _deps_factory(payload: dict) -> DemoWorkflowDependencies:
        job_id = payload.get("_job_id")
        logger: WorkerLogger = WorkerLogger(job_id) if job_id else NullLogger()
        return DemoWorkflowDependencies(
            message=payload.get("message", ""),
            logger=logger,
            storage_ref=payload.get("storage_ref"),
            content_type=payload.get("content_type"),
            byte_size=payload.get("byte_size"),
        )

    def _persist(job_id: str, state: DemoState) -> list[UUID]:
        """Mint the DemoEchoArtifact once the echo state is populated."""
        if state.echoed is None:
            return []
        artifact = DemoEchoArtifact(
            original=state.message or "",
            echoed=state.echoed,
            created_by_job=job_id,
            storage_ref=state.storage_ref,
            content_type=state.content_type,
            byte_size=state.byte_size,
        )
        artifact_api.put(artifact)
        # `artifact_id` is already a UUID (BaseArtifact default_factory);
        # wrapping it in UUID(...) raised. Return it directly.
        return [artifact.artifact_id]

    return JobExecution(
        name="demo",
        graph=demo_graph,
        state_type=DemoState,
        start_node_key="EchoStep",
        node_registry=demo_node_registry,
        deps_factory=_deps_factory,
        extract_result=_extract_demo_result,
        policy=demo_policy,
        persistence=PersistencePolicy(on_complete=_persist),
    )


def register_execution(ctx: BootstrapContext) -> ExecutionDomain:
    return ExecutionDomain(
        name="demo",
        job_executions=[build_demo_execution(ctx.artifact_service, ctx.platform_client)],
        artifact_types=list(DEMO_ARTIFACTS.values()),
    )
