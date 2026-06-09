"""Tests for the ArtifactType catalog.

Mirror of `test_job_definition_catalog`: repository round-trip, service
validation, API CRUD, bundle helper, and the boot-time auto-deploy that
upserts every domain's BaseArtifact subclasses on API startup.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_platform.api.routers import artifact_types as artifact_types_router
from ai_platform.bundle import build_artifact_type_record
from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.artifact_type_service import ArtifactTypeService
from ai_platform.runtime import registry as deps_mod
from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.structured.artifact_type_repository import (
    ArtifactTypeRecord,
    LocalArtifactTypeRepository,
)
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _ToyArtifact(BaseArtifact):
    artifact_type: Literal["toy_artifact"] = "toy_artifact"
    payload: str = ""


class _OtherArtifact(BaseArtifact):
    artifact_type: Literal["other_artifact"] = "other_artifact"
    payload: str = ""


@pytest.fixture
def repo(tmp_path: Path) -> LocalArtifactTypeRepository:
    return LocalArtifactTypeRepository(
        LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifact_types")
    )


@pytest.fixture
def service(repo: LocalArtifactTypeRepository) -> ArtifactTypeService:
    return ArtifactTypeService(repo)


def _record_kwargs(name: str = "toy_artifact", version: str = "1.0.0", **overrides) -> dict:
    base = dict(
        id=ArtifactTypeRecord.make_id(name, version),
        name=name,
        version=version,
        domain="toy",
        class_name="ToyArtifact",
        json_schema={"type": "object", "properties": {}},
        display_hints={},
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


def test_repo_put_then_get_round_trips(repo: LocalArtifactTypeRepository):
    record = ArtifactTypeRecord(**_record_kwargs())
    repo.put(record)
    back = repo.get(record.id)
    assert back.name == "toy_artifact"
    assert back.domain == "toy"


def test_repo_put_is_idempotent_on_id(repo: LocalArtifactTypeRepository):
    repo.put(ArtifactTypeRecord(**_record_kwargs(class_name="first")))
    repo.put(ArtifactTypeRecord(**_record_kwargs(class_name="second")))
    rows = repo.list()
    assert len(rows) == 1
    assert rows[0].class_name == "second"


def test_repo_list_filters_by_domain(repo: LocalArtifactTypeRepository):
    repo.put(ArtifactTypeRecord(**_record_kwargs(name="a", domain="d1")))
    repo.put(ArtifactTypeRecord(**_record_kwargs(name="b", domain="d2")))
    d1_only = repo.list(domain="d1")
    assert [r.name for r in d1_only] == ["a"]


def test_repo_get_by_name_returns_latest(repo: LocalArtifactTypeRepository):
    import time

    repo.put(ArtifactTypeRecord(**_record_kwargs(version="1.0.0", class_name="v1")))
    time.sleep(0.001)  # ensure deployed_at differs
    repo.put(ArtifactTypeRecord(**_record_kwargs(version="2.0.0", class_name="v2")))
    latest = repo.get_by_name("toy_artifact")
    assert latest.version == "2.0.0"


def test_repo_get_missing_raises(repo: LocalArtifactTypeRepository):
    with pytest.raises(ObjectNotFound):
        repo.get("ghost@1.0.0")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_service_deploy_persists(service: ArtifactTypeService):
    out = service.deploy(ArtifactTypeRecord(**_record_kwargs()))
    assert out.id == "toy_artifact@1.0.0"
    assert service.get("toy_artifact@1.0.0").name == "toy_artifact"


def test_service_rejects_empty_name(service: ArtifactTypeService):
    kwargs = _record_kwargs(name="")
    kwargs["id"] = "@1.0.0"
    with pytest.raises(ValueError, match="name must be non-empty"):
        service.deploy(ArtifactTypeRecord(**kwargs))


def test_service_rejects_empty_domain(service: ArtifactTypeService):
    with pytest.raises(ValueError, match="domain must be non-empty"):
        service.deploy(ArtifactTypeRecord(**_record_kwargs(domain="")))


def test_service_rejects_id_mismatch(service: ArtifactTypeService):
    kwargs = _record_kwargs()
    kwargs["id"] = "different@1.0.0"
    with pytest.raises(ValueError, match="doesn't match name@version"):
        service.deploy(ArtifactTypeRecord(**kwargs))


# ---------------------------------------------------------------------------
# Bundle helper — pure builder
# ---------------------------------------------------------------------------


def test_build_artifact_type_record_extracts_schema_from_class():
    record = build_artifact_type_record(_ToyArtifact, domain="toy")
    assert record is not None
    assert record.name == "toy_artifact"
    assert record.domain == "toy"
    assert record.class_name == "_ToyArtifact"
    # The schema is pydantic's JSON Schema for the artifact class.
    assert "properties" in record.json_schema


def test_build_artifact_type_record_skips_class_without_discriminator():
    class _Abstract(BaseArtifact):
        pass

    assert build_artifact_type_record(_Abstract, domain="x") is None


# ---------------------------------------------------------------------------
# API CRUD
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(service: ArtifactTypeService):
    deps_mod._artifact_type_service = service
    app = FastAPI()
    app.include_router(artifact_types_router.router)
    app.dependency_overrides[deps_mod.get_artifact_type_service] = lambda: service
    return TestClient(app)


def test_post_artifact_type_creates_row(api_client, service: ArtifactTypeService):
    record = ArtifactTypeRecord(**_record_kwargs())
    resp = api_client.post("/artifact-types", json=record.model_dump(mode="json"))
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "toy_artifact@1.0.0"
    assert len(service.list()) == 1


def test_post_artifact_type_redeploy_is_idempotent(api_client):
    payload = ArtifactTypeRecord(**_record_kwargs(class_name="v1")).model_dump(mode="json")
    api_client.post("/artifact-types", json=payload)

    payload["class_name"] = "v2"
    resp = api_client.post("/artifact-types", json=payload)
    assert resp.status_code == 201
    assert resp.json()["class_name"] == "v2"

    listing = api_client.get("/artifact-types").json()
    assert len(listing) == 1


def test_get_artifact_types_filters_by_domain(api_client):
    api_client.post(
        "/artifact-types",
        json=ArtifactTypeRecord(**_record_kwargs(name="a", domain="d1")).model_dump(mode="json"),
    )
    api_client.post(
        "/artifact-types",
        json=ArtifactTypeRecord(**_record_kwargs(name="b", domain="d2")).model_dump(mode="json"),
    )
    d1 = api_client.get("/artifact-types?domain=d1").json()
    assert [r["name"] for r in d1] == ["a"]


def test_get_artifact_type_by_name_returns_latest(api_client):
    import time

    api_client.post(
        "/artifact-types",
        json=ArtifactTypeRecord(**_record_kwargs(version="1.0.0", class_name="old")).model_dump(mode="json"),
    )
    time.sleep(0.001)
    api_client.post(
        "/artifact-types",
        json=ArtifactTypeRecord(**_record_kwargs(version="2.0.0", class_name="new")).model_dump(mode="json"),
    )
    resp = api_client.get("/artifact-types/by-name/toy_artifact")
    assert resp.status_code == 200
    assert resp.json()["version"] == "2.0.0"


def test_get_artifact_type_by_name_404s_if_missing(api_client):
    assert api_client.get("/artifact-types/by-name/ghost").status_code == 404


def test_get_artifact_type_by_id_404s_if_missing(api_client):
    assert api_client.get("/artifact-types/ghost@1.0.0").status_code == 404


# ---------------------------------------------------------------------------
# Boot-time auto-deploy through register_control_domains
# ---------------------------------------------------------------------------


def test_register_control_domains_auto_deploys_artifact_types(
    tmp_path: Path, service: ArtifactTypeService
):
    """Boot path: register_control_domains should upsert each domain's
    BaseArtifact subclasses into the catalog. Mirrors the JobDefinition
    auto-deploy.
    """
    from ai_platform.jobs.artifact_service import ArtifactService
    from ai_platform.jobs.bootstrap import register_control_domains
    from ai_platform.jobs.domain import BootstrapContext, ControlDomain
    from ai_platform.jobs.execution_policy import JobControl
    from ai_platform.jobs.input import BaseJobInput
    from ai_platform.jobs.result import BaseJobResult
    from ai_platform.workspace.bootstrap import WorkspaceBootstrap
    from ai_platform.workspace.storage.structured.artifact_repository import (
        LocalArtifactRepository,
    )

    class _Inp(BaseJobInput):
        job_type: Literal["toy"] = "toy"

    class _Res(BaseJobResult):
        job_type: Literal["toy"] = "toy"

    toy_control = JobControl(
        name="toy",
        label="Toy",
        submit_input_type=_Inp,
        result_type=_Res,
        gates=[],
    )

    def fake_register_control(ctx: BootstrapContext) -> ControlDomain:
        return ControlDomain(
            name="toy",
            job_controls=[toy_control],
            artifact_types=[_ToyArtifact, _OtherArtifact],
            runtime_selector="default",
            code_entrypoint="mathai.toy.execution:register_execution",
        )

    artifact_repo = LocalArtifactRepository(
        LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts")
    )
    ws = WorkspaceBootstrap(
        backend="local",
        platform_client=MagicMock(),
        executor=MagicMock(),
        artifact_service=ArtifactService(artifact_repo, registry={}),
        job_definition_service=MagicMock(),  # JobDefinition path is its own test
        artifact_type_service=service,
        code_package_service=MagicMock(),
        media_service=MagicMock(),
        root_dir=str(tmp_path),
    )

    register_control_domains([fake_register_control], ws)
    rows = service.list()
    names = {r.name for r in rows}
    assert names == {"toy_artifact", "other_artifact"}
    assert all(r.domain == "toy" for r in rows)


def test_register_control_domains_swallows_artifact_type_errors(
    tmp_path: Path,
):
    """Best-effort posture: an artifact-type catalog write failure must
    not block API boot.
    """
    from ai_platform.jobs.artifact_service import ArtifactService
    from ai_platform.jobs.bootstrap import register_control_domains
    from ai_platform.jobs.domain import BootstrapContext, ControlDomain
    from ai_platform.jobs.execution_policy import JobControl
    from ai_platform.jobs.input import BaseJobInput
    from ai_platform.jobs.result import BaseJobResult
    from ai_platform.workspace.bootstrap import WorkspaceBootstrap
    from ai_platform.workspace.storage.structured.artifact_repository import (
        LocalArtifactRepository,
    )

    class _Inp(BaseJobInput):
        job_type: Literal["toy"] = "toy"

    class _Res(BaseJobResult):
        job_type: Literal["toy"] = "toy"

    toy_control = JobControl(
        name="toy",
        label="Toy",
        submit_input_type=_Inp,
        result_type=_Res,
        gates=[],
    )

    def fake_register_control(ctx: BootstrapContext) -> ControlDomain:
        return ControlDomain(
            name="toy",
            job_controls=[toy_control],
            artifact_types=[_ToyArtifact],
            runtime_selector="default",
            code_entrypoint="mathai.toy.execution:register_execution",
        )

    bad = MagicMock()
    bad.deploy.side_effect = RuntimeError("DB unreachable")

    artifact_repo = LocalArtifactRepository(
        LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts")
    )
    ws = WorkspaceBootstrap(
        backend="local",
        platform_client=MagicMock(),
        executor=MagicMock(),
        artifact_service=ArtifactService(artifact_repo, registry={}),
        job_definition_service=MagicMock(),
        artifact_type_service=bad,
        code_package_service=MagicMock(),
        media_service=MagicMock(),
        root_dir=str(tmp_path),
    )

    out = register_control_domains([fake_register_control], ws)
    assert "toy" in out.job_controls
    assert bad.deploy.called
