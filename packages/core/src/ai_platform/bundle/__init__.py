"""Bundle deploy — the "give your friend the code" entry point.

A friend with their own domain package runs (effectively):

    from ai_platform.bundle import deploy_control
    from their_domain.control import register_control

    deploy_control(
        register_control,                         # the domain's control register
        runtime="default",
        code_entrypoint="their_domain.execution:register_execution",
        api_url="http://my-platform-instance:8000",
    )

The helper introspects the JobControl(s) the register returns, derives
the schema-shaped JobDefinitionRecord(s), and POSTs each to the
platform API. Idempotent on `(name, version)` — re-running is the
intended redeploy ergonomic.

What lives here:
- `deploy_control(register_control, ...)` — deploy every JobControl
  a domain's `register_control` returns.
- `deploy_job_control(control, ...)` — deploy one JobControl directly
  (useful for tests and for callers that already have the object).
- `build_record(control, ...)` — derive the JobDefinitionRecord
  without POSTing (also useful for tests).

What does NOT live here yet:
- Code packaging / wheel upload (next phase — the entrypoint string
  records the future shape).
- ArtifactType deployment (next phase).
- A YAML or TOML manifest reader (next phase).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import httpx

from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.execution_policy import JobControl
from ai_platform.workspace.storage.structured.artifact_type_repository import (
    ArtifactTypeRecord,
)
from ai_platform.workspace.storage.structured.job_definition_repository import (
    GateSpec,
    JobDefinitionRecord,
)


DEFAULT_API_URL = "http://127.0.0.1:8000"
_TIMEOUT_SECONDS = 10.0


def build_record(
    control: JobControl,
    *,
    runtime: str,
    code_entrypoint: str,
    version: str = "1.0.0",
    artifact_types: tuple[type[BaseArtifact], ...] = (),
) -> JobDefinitionRecord:
    """Derive a JobDefinitionRecord from a live JobControl.

    Pure function — no I/O. Tests can use this to assert the deploy
    payload shape without standing up a server.
    """
    return JobDefinitionRecord(
        id=JobDefinitionRecord.make_id(control.name, version),
        name=control.name,
        version=version,
        runtime_selector=runtime,
        code_entrypoint=code_entrypoint,
        label=control.label,
        input_schema=control.submit_input_type.model_json_schema(),
        result_schema=control.result_type.model_json_schema(),
        output_artifact_type_refs=[
            cls.model_fields["artifact_type"].default for cls in artifact_types
        ],
        gates=[
            GateSpec(
                node_name=g.node_name,
                review_type_name=g.review_type.__name__,
                review_schema=g.review_type.model_json_schema(),
            )
            for g in control.gates
        ],
    )


def deploy_job_control(
    control: JobControl,
    *,
    runtime: str,
    code_entrypoint: str,
    version: str = "1.0.0",
    artifact_types: tuple[type[BaseArtifact], ...] = (),
    api_url: str = DEFAULT_API_URL,
) -> JobDefinitionRecord:
    """Build the record and POST it to `/job-definitions`. Returns the
    server's persisted view (deployed_at populated by the server).
    """
    record = build_record(
        control,
        runtime=runtime,
        code_entrypoint=code_entrypoint,
        version=version,
        artifact_types=artifact_types,
    )
    response = httpx.post(
        f"{api_url.rstrip('/')}/job-definitions",
        json=record.model_dump(mode="json"),
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return JobDefinitionRecord.model_validate(response.json())


def build_artifact_type_record(
    artifact_cls: type[BaseArtifact],
    *,
    domain: str,
    version: str = "1.0.0",
) -> Optional[ArtifactTypeRecord]:
    """Derive an ArtifactTypeRecord from a BaseArtifact subclass.

    Returns `None` when the class has no `artifact_type` discriminator
    default (i.e. abstract). Pure function — no I/O. Tests + the auto-
    deploy path both use this so the on-disk shape stays consistent.
    """
    field = artifact_cls.model_fields.get("artifact_type")
    if field is None:
        return None
    name = field.default
    if not isinstance(name, str) or not name:
        return None
    return ArtifactTypeRecord(
        id=ArtifactTypeRecord.make_id(name, version),
        name=name,
        version=version,
        domain=domain,
        class_name=artifact_cls.__name__,
        json_schema=artifact_cls.model_json_schema(),
    )


def deploy_artifact_type(
    artifact_cls: type[BaseArtifact],
    *,
    domain: str,
    version: str = "1.0.0",
    api_url: str = DEFAULT_API_URL,
) -> ArtifactTypeRecord:
    """Build the record and POST it to `/artifact-types`."""
    record = build_artifact_type_record(artifact_cls, domain=domain, version=version)
    if record is None:
        raise ValueError(
            f"{artifact_cls.__name__} has no `artifact_type` discriminator default"
        )
    response = httpx.post(
        f"{api_url.rstrip('/')}/artifact-types",
        json=record.model_dump(mode="json"),
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return ArtifactTypeRecord.model_validate(response.json())


def deploy_control(
    register_control: Callable[[Any], Any],
    *,
    runtime: str,
    code_entrypoint: str,
    bootstrap_ctx: Optional[Any] = None,
    version: str = "1.0.0",
    api_url: str = DEFAULT_API_URL,
) -> list[JobDefinitionRecord]:
    """Deploy every JobControl that a domain's `register_control` returns.

    `register_control` is the domain's `register_control(ctx) -> ControlDomain`.
    We synthesize a minimal `BootstrapContext` if the caller doesn't pass
    one — for deploy-time use, the JobControl doesn't actually exercise
    the bootstrap services, so a stub suffices.
    """
    from dataclasses import dataclass

    if bootstrap_ctx is None:
        # Stand-in for `ai_platform.jobs.domain.BootstrapContext`. The
        # register_control call only needs the dataclass-shape; it
        # doesn't invoke any services at deploy time.
        @dataclass
        class _StubCtx:
            platform_client: Any = None
            backend: str = "stub"
            artifact_service: Any = None
            root_dir: Optional[str] = None

        bootstrap_ctx = _StubCtx()

    control_domain = register_control(bootstrap_ctx)
    artifact_types_by_owner = tuple(control_domain.artifact_types)

    deployed: list[JobDefinitionRecord] = []
    for control in control_domain.job_controls:
        deployed.append(
            deploy_job_control(
                control,
                runtime=runtime,
                code_entrypoint=code_entrypoint,
                version=version,
                artifact_types=artifact_types_by_owner,
                api_url=api_url,
            )
        )
    return deployed
