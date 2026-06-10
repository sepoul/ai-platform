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
- `deploy_bundle(manifest, ...)` — read `bundle.toml`, upload the wheel,
  register every JobDefinition + ArtifactType (the full deploy).
- `declare_artifacts(manifest, ...)` — register **only** the artifact
  types (the contract): no wheel, no job. Contract-first deploy so the
  SDK can regenerate and frontend + backend build in parallel before the
  implementation ships (see `sdk-contract-first-plan.md`).
- `deploy_control` / `deploy_job_control` / `build_record` — JobDefinition
  primitives (one register / one control / pure record builder).
- `deploy_artifact_type` / `declare_artifact_types` — ArtifactType
  primitives (one class / a register's whole set).
- `deploy_code_package(wheel, ...)` — multipart wheel upload.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

import httpx

from pathlib import Path

from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.execution_policy import JobControl
from ai_platform.workspace.storage.structured.artifact_type_repository import (
    ArtifactTypeRecord,
)
from ai_platform.workspace.storage.structured.code_package_repository import (
    CodePackageRecord,
)
from ai_platform.workspace.storage.structured.job_definition_repository import (
    GateSpec,
    JobDefinitionRecord,
)


DEFAULT_API_URL = "http://127.0.0.1:8000"
_TIMEOUT_SECONDS = 10.0


def _stub_bootstrap_ctx() -> Any:
    """Minimal stand-in for `ai_platform.jobs.domain.BootstrapContext`.

    A domain's `register_control(ctx)` only needs the dataclass shape at
    deploy time — it introspects types and never exercises the bootstrap
    services — so a stub with the right attributes suffices.
    """
    from dataclasses import dataclass

    @dataclass
    class _StubCtx:
        platform_client: Any = None
        backend: str = "stub"
        artifact_service: Any = None
        root_dir: Optional[str] = None

    return _StubCtx()


def _post_artifact_type_record(
    record: ArtifactTypeRecord, *, api_url: str = DEFAULT_API_URL
) -> ArtifactTypeRecord:
    """POST one ArtifactTypeRecord to `/artifact-types`. Idempotent on
    `(name, version)` server-side."""
    response = httpx.post(
        f"{api_url.rstrip('/')}/artifact-types",
        json=record.model_dump(mode="json"),
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return ArtifactTypeRecord.model_validate(response.json())


def build_record(
    control: JobControl,
    *,
    runtime: str,
    code_entrypoint: str,
    control_entrypoint: str = "",
    version: str = "1.0.0",
    artifact_types: tuple[type[BaseArtifact], ...] = (),
) -> JobDefinitionRecord:
    """Derive a JobDefinitionRecord from a live JobControl.

    Pure function — no I/O. Tests can use this to assert the deploy
    payload shape without standing up a server.

    `control_entrypoint` is the platform-discovery seam: the API reads
    JobDefinition rows on boot, dedups by this field, and pip-imports
    each callable to register its control plane. Leave empty for rows
    that originate from in-process auto-deploy on a domain that didn't
    self-describe (older bootstrap shapes); the API falls back to
    composition_root in that case.
    """
    return JobDefinitionRecord(
        id=JobDefinitionRecord.make_id(control.name, version),
        name=control.name,
        version=version,
        runtime_selector=runtime,
        code_entrypoint=code_entrypoint,
        control_entrypoint=control_entrypoint,
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
    control_entrypoint: str = "",
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
        control_entrypoint=control_entrypoint,
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
    return _post_artifact_type_record(record, api_url=api_url)


def declare_artifact_types(
    register_control: Callable[[Any], Any],
    *,
    domain: str,
    version: str = "1.0.0",
    api_url: str = DEFAULT_API_URL,
) -> list[ArtifactTypeRecord]:
    """Register *only* the artifact types a domain's `register_control`
    declares — the contract — with no wheel upload and no job definition.

    Contract-first deploy: publishing the artifact JSON Schemas early lets
    the SDK regenerate, so the producing job and any consuming UI can be
    built in parallel against typed shapes before the implementation ships
    (see `sdk-contract-first-plan.md`). Idempotent on `(name, version)`;
    abstract classes (no `artifact_type` discriminator default) are
    skipped, matching `deploy_bundle`'s resilience.
    """
    control_domain = register_control(_stub_bootstrap_ctx())
    deployed: list[ArtifactTypeRecord] = []
    for artifact_cls in control_domain.artifact_types:
        record = build_artifact_type_record(artifact_cls, domain=domain, version=version)
        if record is None:
            continue
        deployed.append(_post_artifact_type_record(record, api_url=api_url))
    return deployed


def deploy_code_package(
    wheel_path: str | Path,
    *,
    name: str,
    version: str = "1.0.0",
    runtime_selector: str,
    api_url: str = DEFAULT_API_URL,
) -> CodePackageRecord:
    """Upload a `.whl` to `/code-packages` as multipart.

    Pure HTTP — no Python install on the calling side. The platform
    stores the bytes via its FileRepository and records a
    `CodePackageRecord`. Idempotent on `(name, version)` — re-uploading
    overwrites both blob and row.
    """
    path = Path(wheel_path)
    if not path.exists():
        raise FileNotFoundError(f"Wheel not found: {path}")
    with path.open("rb") as fh:
        files = {"wheel": (path.name, fh, "application/octet-stream")}
        data = {"name": name, "version": version, "runtime_selector": runtime_selector}
        response = httpx.post(
            f"{api_url.rstrip('/')}/code-packages",
            files=files,
            data=data,
            timeout=_TIMEOUT_SECONDS,
        )
    response.raise_for_status()
    return CodePackageRecord.model_validate(response.json())


def snapshot_openapi(
    api_url: str = DEFAULT_API_URL,
    *,
    out_path: str | Path = "sdk-ts/openapi.snapshot.json",
) -> Path:
    """Fetch `/openapi.json` from a running platform and write it to a file.

    Run this where you can reach the deployment (e.g. on the tailnet), then
    commit the result. The SDK-regen workflow transforms the committed
    snapshot into `schema.d.ts` with no privileged network access — the
    only step that touches the box is this dump, run by someone already
    trusted to reach it. See `sdk-contract-first-plan.md` and
    `docs/guides/sdk-and-types.md`.

    Returns the path written.
    """
    response = httpx.get(
        f"{api_url.rstrip('/')}/openapi.json", timeout=_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(response.json(), indent=2) + "\n", encoding="utf-8")
    return out


def deploy_control(
    register_control: Callable[[Any], Any],
    *,
    runtime: str,
    code_entrypoint: str,
    control_entrypoint: str = "",
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
    if bootstrap_ctx is None:
        bootstrap_ctx = _stub_bootstrap_ctx()

    control_domain = register_control(bootstrap_ctx)
    artifact_types_by_owner = tuple(control_domain.artifact_types)
    # Prefer the explicitly-passed value (bundle.toml flow), else fall
    # back to what the domain self-described.
    effective_control_entrypoint = (
        control_entrypoint or getattr(control_domain, "control_entrypoint", "")
    )

    deployed: list[JobDefinitionRecord] = []
    for control in control_domain.job_controls:
        deployed.append(
            deploy_job_control(
                control,
                runtime=runtime,
                code_entrypoint=code_entrypoint,
                control_entrypoint=effective_control_entrypoint,
                version=version,
                artifact_types=artifact_types_by_owner,
                api_url=api_url,
            )
        )
    return deployed


# ---------------------------------------------------------------------------
# Bundle deploy — manifest-driven orchestration over the three primitives.
# ---------------------------------------------------------------------------


def _resolve_entrypoint(entrypoint: str) -> Callable[[Any], Any]:
    """Resolve a "module.path:callable" entrypoint string.

    Pure import — raises ImportError / AttributeError on failure, which
    the CLI surfaces with the original message rather than wrapping.
    """
    if ":" not in entrypoint:
        raise ValueError(
            f"Entrypoint {entrypoint!r} must be 'package.module:callable'"
        )
    module_path, attr = entrypoint.split(":", 1)
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, attr)


def deploy_bundle(
    manifest_path: str | Path,
    *,
    api_url: str = DEFAULT_API_URL,
) -> dict[str, Any]:
    """Read `bundle.toml`, upload the wheel, and register every
    JobDefinition + ArtifactType the bundle's control entrypoint
    declares.

    Order matters: CodePackage first (so a worker booted between this
    and the JobDefinition deploy already has the install rule), then
    JobDefinitions + ArtifactTypes (which reference the package by
    `code_entrypoint`).

    Each underlying call is idempotent on `(name, version)`. A failure
    midway leaves the platform in a partially-deployed but recoverable
    state: re-running picks up where we left off (no duplicate rows,
    no orphan blobs).

    Returns a small report dict suitable for printing from the CLI.
    """
    from ai_platform.bundle.manifest import BundleManifest

    manifest = BundleManifest.load(manifest_path)
    wheel_path = manifest.wheel_path(manifest_path)

    # 1. CodePackage — bytes must land before any JobDefinition can
    #    reference the entrypoint that lives inside the wheel.
    code_pkg = deploy_code_package(
        wheel_path,
        name=manifest.package.name,
        version=manifest.package.version,
        runtime_selector=manifest.package.runtime,
        api_url=api_url,
    )

    # 2. Resolve the control entrypoint in-process to introspect the
    #    JobControls + artifact types the wheel declares. The
    #    execution entrypoint is NOT resolved here — it's a string
    #    handed to the worker, which resolves it after install.
    register_control = _resolve_entrypoint(manifest.control.control_entrypoint)
    job_defs = deploy_control(
        register_control,
        runtime=manifest.package.runtime,
        code_entrypoint=manifest.control.execution_entrypoint,
        control_entrypoint=manifest.control.control_entrypoint,
        version=manifest.package.version,
        api_url=api_url,
    )

    # 3. ArtifactTypes — same control entrypoint, separate POSTs.
    artifact_types = declare_artifact_types(
        register_control,
        domain=manifest.control.domain,
        version=manifest.package.version,
        api_url=api_url,
    )

    return {
        "code_package": code_pkg.id,
        "job_definitions": [jd.id for jd in job_defs],
        "artifact_types": [at.id for at in artifact_types],
    }


def declare_artifacts(
    manifest_path: str | Path,
    *,
    api_url: str = DEFAULT_API_URL,
) -> dict[str, Any]:
    """Contract-first counterpart to `deploy_bundle`: register *only* the
    bundle's artifact types (the contract), skipping the wheel upload and
    job-definition registration.

    Resolves the bundle's `control_entrypoint` in-process (the domain
    package must be importable) to introspect `ControlDomain.artifact_types`,
    then POSTs each to `/artifact-types`. Use it to publish artifact shapes
    early — before the job implementation or even its wheel exists — so the
    SDK can regenerate and frontend + backend proceed in parallel (see
    `sdk-contract-first-plan.md`). Idempotent on `(name, version)`.
    """
    from ai_platform.bundle.manifest import BundleManifest

    manifest = BundleManifest.load(manifest_path)
    register_control = _resolve_entrypoint(manifest.control.control_entrypoint)
    artifact_types = declare_artifact_types(
        register_control,
        domain=manifest.control.domain,
        version=manifest.package.version,
        api_url=api_url,
    )
    return {"artifact_types": [at.id for at in artifact_types]}
