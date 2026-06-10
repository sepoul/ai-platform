"""End-to-end tests for `aiplatform deploy` — the bundle.toml CLI.

Layered:
1. BundleManifest — parse + wheel path resolution + validation.
2. Entrypoint resolver — happy + bad format.
3. deploy_bundle — orchestration order, multiplexed through a real
   FastAPI TestClient that wires up all three routers; uses a tiny
   `register_control` shim as the bundle's control entrypoint.
4. CLI — main(["deploy", ...]) exits 0 on success, 2 on missing
   manifest, 1 on deploy failure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_platform.api.routers import artifact_types as artifact_types_router
from ai_platform.api.routers import code_packages as code_pkgs_router
from ai_platform.api.routers import job_definitions as job_defs_router
from ai_platform.bundle import (
    _resolve_entrypoint,
    cli,
    declare_artifact_types,
    declare_artifacts,
    deploy_bundle,
)
from ai_platform.bundle.manifest import BundleManifest
from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.artifact_type_service import ArtifactTypeService
from ai_platform.jobs.code_package_service import CodePackageService
from ai_platform.jobs.execution_policy import JobControl
from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.job_definition_service import JobDefinitionService
from ai_platform.jobs.result import BaseJobResult
from ai_platform.runtime import registry as deps_mod
from ai_platform.workspace.storage.blobs.local import (
    LocalFileRepository,
    LocalFileRepositoryConfig,
)
from ai_platform.workspace.storage.structured.artifact_type_repository import (
    LocalArtifactTypeRepository,
)
from ai_platform.workspace.storage.structured.code_package_repository import (
    LocalCodePackageRepository,
)
from ai_platform.workspace.storage.structured.job_definition_repository import (
    LocalJobDefinitionRepository,
)
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def _write_manifest(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "bundle.toml"
    path.write_text(body)
    return path


def test_manifest_parses_valid_toml(tmp_path: Path):
    path = _write_manifest(tmp_path, """
[package]
name = "mathai-math-qa"
version = "1.0.0"
runtime = "default"
wheel = "dist/mathai_math_qa-1.0.0-py3-none-any.whl"

[control]
domain = "math_qa"
control_entrypoint = "mathai.math_qa.control:register_control"
execution_entrypoint = "mathai.math_qa.execution:register_execution"
""")
    m = BundleManifest.load(path)
    assert m.package.name == "mathai-math-qa"
    assert m.package.runtime == "default"
    assert m.control.domain == "math_qa"


def test_manifest_resolves_wheel_path_relative_to_manifest(tmp_path: Path):
    path = _write_manifest(tmp_path, """
[package]
name = "x"
version = "1.0.0"
runtime = "default"
wheel = "out/x-1.0.0.whl"

[control]
domain = "x"
control_entrypoint = "x:r"
execution_entrypoint = "x:e"
""")
    m = BundleManifest.load(path)
    # Absolute path, anchored at the manifest's directory.
    assert m.wheel_path(path) == (tmp_path / "out" / "x-1.0.0.whl").resolve()


def test_manifest_rejects_unknown_section(tmp_path: Path):
    path = _write_manifest(tmp_path, """
[package]
name = "x"
version = "1.0.0"
runtime = "default"
wheel = "x.whl"

[control]
domain = "x"
control_entrypoint = "x:r"
execution_entrypoint = "x:e"

[mystery]
foo = "bar"
""")
    with pytest.raises(Exception):  # pydantic ValidationError
        BundleManifest.load(path)


def test_manifest_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        BundleManifest.load(tmp_path / "nope.toml")


# ---------------------------------------------------------------------------
# Entrypoint resolver
# ---------------------------------------------------------------------------


def test_resolve_entrypoint_returns_callable():
    # `BundleManifest.load` is a classmethod — perfect target for "is callable".
    fn = _resolve_entrypoint("ai_platform.bundle.manifest:BundleManifest")
    assert fn is BundleManifest


def test_resolve_entrypoint_rejects_bad_format():
    with pytest.raises(ValueError, match="package.module:callable"):
        _resolve_entrypoint("not.a.real.path")


# ---------------------------------------------------------------------------
# Fixtures for end-to-end bundle deploy
# ---------------------------------------------------------------------------


# A toy bundle's "control" entrypoint — the manifest will reference it
# by its dotted path. Lives at module scope so importlib can find it.
class _ToyInput(BaseJobInput):
    job_type: Literal["toy"] = "toy"


class _ToyResult(BaseJobResult):
    job_type: Literal["toy"] = "toy"


class _ToyArtifact(BaseArtifact):
    artifact_type: Literal["toy_artifact"] = "toy_artifact"


def toy_register_control(ctx):  # noqa: ARG001
    """Bundle-test register_control. Module path:
    `tests.test_bundle_deploy:toy_register_control`.
    """
    from ai_platform.jobs.domain import ControlDomain
    from ai_platform.jobs.execution_policy import JobControl as _JC

    return ControlDomain(
        name="toy",
        job_controls=[
            _JC(
                name="toy",
                label="Toy",
                submit_input_type=_ToyInput,
                result_type=_ToyResult,
                gates=[],
            )
        ],
        artifact_types=[_ToyArtifact],
        runtime_selector="default",
        code_entrypoint="tests.test_bundle_deploy:toy_register_execution",
    )


def toy_register_execution(ctx):  # noqa: ARG001 — never called at deploy time
    raise NotImplementedError


@pytest.fixture
def services(tmp_path: Path):
    """Wire up all three services on a tmp_path-backed local backend."""
    file_repo = LocalFileRepository(
        LocalFileRepositoryConfig(root_dir=str(tmp_path), prefix="files")
    )
    jd_svc = JobDefinitionService(
        LocalJobDefinitionRepository(
            LocalRepositoryConfig(root_dir=str(tmp_path), prefix="job_definitions")
        )
    )
    at_svc = ArtifactTypeService(
        LocalArtifactTypeRepository(
            LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifact_types")
        )
    )
    cp_svc = CodePackageService(
        LocalCodePackageRepository(
            LocalRepositoryConfig(root_dir=str(tmp_path), prefix="code_packages")
        ),
        file_repo,
    )
    return jd_svc, at_svc, cp_svc


@pytest.fixture
def api_client(services):
    jd_svc, at_svc, cp_svc = services
    deps_mod._job_definition_service = jd_svc
    deps_mod._artifact_type_service = at_svc
    deps_mod._code_package_service = cp_svc

    app = FastAPI()
    app.include_router(job_defs_router.router)
    app.include_router(artifact_types_router.router)
    app.include_router(code_pkgs_router.router)
    app.dependency_overrides[deps_mod.get_job_definition_service] = lambda: jd_svc
    app.dependency_overrides[deps_mod.get_artifact_type_service] = lambda: at_svc
    app.dependency_overrides[deps_mod.get_code_package_service] = lambda: cp_svc
    return TestClient(app)


@pytest.fixture
def bundle_manifest(tmp_path: Path) -> Path:
    """Write a bundle.toml + a tiny wheel into tmp_path."""
    wheel = tmp_path / "toy_pkg-1.0.0-py3-none-any.whl"
    wheel.write_bytes(b"PK\x03\x04toy-wheel-bytes")
    manifest = tmp_path / "bundle.toml"
    manifest.write_text(f"""
[package]
name = "toy_pkg"
version = "1.0.0"
runtime = "default"
wheel = "{wheel.name}"

[control]
domain = "toy"
control_entrypoint = "tests.test_bundle_deploy:toy_register_control"
execution_entrypoint = "tests.test_bundle_deploy:toy_register_execution"
""")
    return manifest


# ---------------------------------------------------------------------------
# deploy_bundle end-to-end
# ---------------------------------------------------------------------------


def _route_httpx_through_testclient(monkeypatch, api_client: TestClient):
    """Make `httpx.post` (used by the bundle helpers) hit the in-process
    FastAPI TestClient instead of a real network.
    """
    import ai_platform.bundle as bundle_mod

    def fake_post(url, json=None, files=None, data=None, timeout=None):  # noqa: ARG001
        path = url.split("://", 1)[1].split("/", 1)[1]
        path = "/" + path
        if files is not None:
            fname, fh, ctype = files["wheel"]
            files_for_client = {"wheel": (fname, fh.read() if hasattr(fh, "read") else fh, ctype)}
            resp = api_client.post(path, files=files_for_client, data=data)
        else:
            resp = api_client.post(path, json=json)

        class _R:
            status_code = resp.status_code

            def raise_for_status(self):
                resp.raise_for_status()

            def json(self):
                return resp.json()

        return _R()

    monkeypatch.setattr(bundle_mod.httpx, "post", fake_post)


def test_deploy_bundle_uploads_wheel_and_deploys_all_records(
    api_client, services, bundle_manifest, monkeypatch
):
    jd_svc, at_svc, cp_svc = services
    _route_httpx_through_testclient(monkeypatch, api_client)

    report = deploy_bundle(bundle_manifest, api_url="http://fake")

    assert report["code_package"] == "toy_pkg@1.0.0"
    assert report["job_definitions"] == ["toy@1.0.0"]
    assert report["artifact_types"] == ["toy_artifact@1.0.0"]

    # State actually landed in the services.
    assert cp_svc.get("toy_pkg@1.0.0").runtime_selector == "default"
    jd = jd_svc.get("toy@1.0.0")
    assert jd.runtime_selector == "default"
    assert jd.code_entrypoint == "tests.test_bundle_deploy:toy_register_execution"
    assert at_svc.get("toy_artifact@1.0.0").domain == "toy"


def test_deploy_bundle_is_idempotent_on_rerun(
    api_client, services, bundle_manifest, monkeypatch
):
    """Re-running the same bundle must overwrite (not duplicate) every row."""
    jd_svc, at_svc, cp_svc = services
    _route_httpx_through_testclient(monkeypatch, api_client)

    deploy_bundle(bundle_manifest, api_url="http://fake")
    deploy_bundle(bundle_manifest, api_url="http://fake")

    assert len(cp_svc.list()) == 1
    assert len(jd_svc.list()) == 1
    assert len(at_svc.list()) == 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_main_deploy_returns_0_on_success(
    api_client, bundle_manifest, monkeypatch, capsys
):
    _route_httpx_through_testclient(monkeypatch, api_client)
    rc = cli.main(["deploy", "--bundle", str(bundle_manifest), "--api-url", "http://fake"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "CodePackage:    toy_pkg@1.0.0" in out
    assert "JobDefinition:  toy@1.0.0" in out
    assert "ArtifactType:   toy_artifact@1.0.0" in out


def test_cli_main_returns_2_on_missing_manifest(tmp_path: Path, capsys):
    missing = tmp_path / "no-such-bundle.toml"
    rc = cli.main(["deploy", "--bundle", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not found" in err


def test_cli_main_returns_1_on_deploy_failure(
    bundle_manifest, monkeypatch, capsys
):
    """If the orchestration raises (e.g. API unreachable), the CLI must
    surface the message to stderr and exit non-zero.
    """
    def boom(*_args, **_kw):
        raise RuntimeError("api unreachable")

    monkeypatch.setattr("ai_platform.bundle.cli.deploy_bundle", boom)
    rc = cli.main(["deploy", "--bundle", str(bundle_manifest)])
    assert rc == 1
    assert "api unreachable" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# declare-artifacts — contract-first (artifact types only, no wheel/job)
# ---------------------------------------------------------------------------


def test_declare_artifacts_posts_only_artifact_types(
    api_client, services, bundle_manifest, monkeypatch
):
    """The whole point of the split: declaring the contract registers the
    artifact types and touches NEITHER code_packages NOR job_definitions.
    """
    jd_svc, at_svc, cp_svc = services
    _route_httpx_through_testclient(monkeypatch, api_client)

    report = declare_artifacts(bundle_manifest, api_url="http://fake")

    assert report["artifact_types"] == ["toy_artifact@1.0.0"]
    assert at_svc.get("toy_artifact@1.0.0").domain == "toy"
    # No wheel, no job — the contract shipped alone.
    assert cp_svc.list() == []
    assert jd_svc.list() == []


def test_declare_artifacts_works_without_a_wheel(
    api_client, services, tmp_path, monkeypatch
):
    """Contract-first means publishing artifact shapes before the wheel is
    even built — `declare_artifacts` never reads it.
    """
    _jd, _at, cp_svc = services
    _route_httpx_through_testclient(monkeypatch, api_client)

    manifest = tmp_path / "bundle.toml"
    manifest.write_text("""
[package]
name = "toy_pkg"
version = "1.0.0"
runtime = "default"
wheel = "dist/never-built.whl"

[control]
domain = "toy"
control_entrypoint = "tests.test_bundle_deploy:toy_register_control"
execution_entrypoint = "tests.test_bundle_deploy:toy_register_execution"
""")
    # Wheel path points at a file that does not exist — declare succeeds.
    report = declare_artifacts(manifest, api_url="http://fake")
    assert report["artifact_types"] == ["toy_artifact@1.0.0"]
    assert cp_svc.list() == []


def test_declare_artifact_types_from_register(api_client, services, monkeypatch):
    _jd, at_svc, _cp = services
    _route_httpx_through_testclient(monkeypatch, api_client)

    records = declare_artifact_types(
        toy_register_control, domain="toy", api_url="http://fake"
    )
    assert [r.id for r in records] == ["toy_artifact@1.0.0"]
    assert at_svc.get("toy_artifact@1.0.0").class_name == "_ToyArtifact"


def test_declare_artifacts_is_idempotent(
    api_client, services, bundle_manifest, monkeypatch
):
    _jd, at_svc, _cp = services
    _route_httpx_through_testclient(monkeypatch, api_client)

    declare_artifacts(bundle_manifest, api_url="http://fake")
    declare_artifacts(bundle_manifest, api_url="http://fake")
    assert len(at_svc.list()) == 1


def test_cli_declare_artifacts_prints_only_artifacts(
    api_client, bundle_manifest, monkeypatch, capsys
):
    _route_httpx_through_testclient(monkeypatch, api_client)
    rc = cli.main(
        ["declare-artifacts", "--bundle", str(bundle_manifest), "--api-url", "http://fake"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "ArtifactType:   toy_artifact@1.0.0" in out
    # Contract-only path — no wheel/job lines.
    assert "CodePackage" not in out
    assert "JobDefinition" not in out


def test_cli_declare_artifacts_missing_manifest_returns_2(tmp_path: Path, capsys):
    rc = cli.main(["declare-artifacts", "--bundle", str(tmp_path / "nope.toml")])
    assert rc == 2
    assert "not found" in capsys.readouterr().err
