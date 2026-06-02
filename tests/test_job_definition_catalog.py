"""Tests for the JobDefinition catalog — the bundle-deploy substrate.

Three layers:
1. **Repository (local backend)** — round-trip, idempotent put,
   list filters, get_by_name returns the latest.
2. **Service** — runtime-selector validation, id-vs-name@version
   consistency check, idempotency.
3. **API + bundle helper** — POST /job-definitions accepts a record,
   list / get-by-name / get-by-id all work; the bundle helper builds
   a record from a live JobControl and POSTs it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from ai_platform.bundle import build_record, deploy_job_control
from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.execution_policy import JobControl, NodeGate
from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.job_definition_service import JobDefinitionService
from ai_platform.jobs.result import BaseJobResult
from ai_platform.runtime import registry as deps_mod
from ai_platform.api.routers import job_definitions as job_defs_router
from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.structured.job_definition_repository import (
    GateSpec,
    JobDefinitionRecord,
    LocalJobDefinitionRepository,
)
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig


# ---------------------------------------------------------------------------
# Fixtures — tiny synthetic JobControl that doesn't pull a domain
# ---------------------------------------------------------------------------


class _ToyInput(BaseJobInput):
    job_type: Literal["toy"] = "toy"
    question: str


class _ToyResult(BaseJobResult):
    job_type: Literal["toy"] = "toy"
    answer: str | None = None


class _ToyArtifact(BaseArtifact):
    artifact_type: Literal["toy_artifact"] = "toy_artifact"


class _ReviewBody(BaseModel):
    rating: int


@pytest.fixture
def repo(tmp_path: Path) -> LocalJobDefinitionRepository:
    return LocalJobDefinitionRepository(
        LocalRepositoryConfig(root_dir=str(tmp_path), prefix="job_definitions")
    )


@pytest.fixture
def service(repo: LocalJobDefinitionRepository) -> JobDefinitionService:
    return JobDefinitionService(repo)


@pytest.fixture
def toy_control() -> JobControl:
    return JobControl(
        name="toy",
        label="Toy job",
        submit_input_type=_ToyInput,
        result_type=_ToyResult,
        gates=[NodeGate(node_name="Review", review_type=_ReviewBody)],
    )


def _record_kwargs(name: str = "toy", version: str = "1.0.0", **overrides) -> dict:
    base = dict(
        id=JobDefinitionRecord.make_id(name, version),
        name=name,
        version=version,
        runtime_selector="default",
        code_entrypoint="mathai.toy.execution:register_execution",
        label="Toy",
        input_schema={"type": "object"},
        result_schema={"type": "object"},
        output_artifact_type_refs=[],
        gates=[],
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


def test_repo_put_then_get_round_trips(repo: LocalJobDefinitionRepository):
    record = JobDefinitionRecord(**_record_kwargs())
    repo.put(record)
    back = repo.get(record.id)
    assert back.name == "toy"
    assert back.runtime_selector == "default"


def test_repo_put_is_idempotent_on_id(repo: LocalJobDefinitionRepository):
    """Re-putting the same id overwrites in place; no duplicate row."""
    repo.put(JobDefinitionRecord(**_record_kwargs(label="first")))
    repo.put(JobDefinitionRecord(**_record_kwargs(label="second")))
    rows = repo.list()
    assert len(rows) == 1
    assert rows[0].label == "second"


def test_repo_list_filters_by_runtime(repo: LocalJobDefinitionRepository):
    repo.put(JobDefinitionRecord(**_record_kwargs(name="default-job", runtime_selector="default")))
    repo.put(JobDefinitionRecord(**_record_kwargs(name="crewai-job", runtime_selector="crewai")))
    crewai = repo.list(runtime_selector="crewai")
    assert {r.name for r in crewai} == {"crewai-job"}


def test_repo_get_by_name_returns_latest_deployed(repo: LocalJobDefinitionRepository):
    """When multiple versions exist, get_by_name returns the most
    recently deployed (the contract the API will route against
    post-cutover).
    """
    import time

    repo.put(JobDefinitionRecord(**_record_kwargs(version="1.0.0", label="old")))
    time.sleep(0.01)  # ensure timestamp ordering is stable
    repo.put(JobDefinitionRecord(**_record_kwargs(version="2.0.0", label="new")))
    latest = repo.get_by_name("toy")
    assert latest.version == "2.0.0"
    assert latest.label == "new"


def test_repo_get_missing_raises(repo: LocalJobDefinitionRepository):
    with pytest.raises(ObjectNotFound):
        repo.get("nonexistent@1.0.0")


def test_repo_get_by_name_missing_raises(repo: LocalJobDefinitionRepository):
    with pytest.raises(ObjectNotFound):
        repo.get_by_name("nonexistent")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_service_deploy_records_the_row(service: JobDefinitionService):
    out = service.deploy(JobDefinitionRecord(**_record_kwargs()))
    assert out.id == "toy@1.0.0"
    # Idempotent — calling twice doesn't duplicate.
    service.deploy(JobDefinitionRecord(**_record_kwargs(label="updated")))
    assert len(service.list()) == 1


def test_service_rejects_unknown_runtime(service: JobDefinitionService):
    with pytest.raises(ValueError, match="Unknown runtime_selector"):
        service.deploy(
            JobDefinitionRecord(**_record_kwargs(runtime_selector="not-a-runtime"))
        )


def test_service_rejects_id_mismatch(service: JobDefinitionService):
    """The id must equal "name@version". Pre-computing a divergent id
    would otherwise let a caller silently overwrite an unrelated row.
    """
    kwargs = _record_kwargs()
    kwargs["id"] = "different@1.0.0"
    with pytest.raises(ValueError, match="doesn't match name@version"):
        service.deploy(JobDefinitionRecord(**kwargs))


# ---------------------------------------------------------------------------
# Bundle helper — pure builder (no I/O)
# ---------------------------------------------------------------------------


def test_build_record_extracts_schemas_from_control(toy_control: JobControl):
    record = build_record(
        toy_control,
        runtime="default",
        code_entrypoint="mathai.toy.execution:register_execution",
        artifact_types=(_ToyArtifact,),
    )
    assert record.name == "toy"
    assert record.version == "1.0.0"
    assert record.id == "toy@1.0.0"
    # Input schema is the pydantic JSON Schema — has the discriminator.
    assert "properties" in record.input_schema
    assert "question" in record.input_schema["properties"]
    # Gates extracted with the review's JSON Schema.
    assert len(record.gates) == 1
    assert record.gates[0].node_name == "Review"
    assert record.gates[0].review_type_name == "_ReviewBody"
    assert "rating" in record.gates[0].review_schema["properties"]
    # Artifact type refs by discriminator string.
    assert record.output_artifact_type_refs == ["toy_artifact"]


# ---------------------------------------------------------------------------
# API + bundle deploy end-to-end through a TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(tmp_path: Path, service: JobDefinitionService):
    deps_mod._job_definition_service = service  # bypass init_platform
    app = FastAPI()
    app.include_router(job_defs_router.router)
    app.dependency_overrides[deps_mod.get_job_definition_service] = lambda: service
    return TestClient(app)


def test_post_job_definition_creates_row(api_client, service: JobDefinitionService):
    record = JobDefinitionRecord(**_record_kwargs())
    resp = api_client.post("/job-definitions", json=record.model_dump(mode="json"))
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "toy@1.0.0"
    assert len(service.list()) == 1


def test_post_job_definition_redeploy_is_idempotent(api_client):
    payload = JobDefinitionRecord(**_record_kwargs(label="v1")).model_dump(mode="json")
    api_client.post("/job-definitions", json=payload)

    payload["label"] = "v2"
    resp = api_client.post("/job-definitions", json=payload)
    assert resp.status_code == 201
    assert resp.json()["label"] == "v2"

    listing = api_client.get("/job-definitions").json()
    assert len(listing) == 1
    assert listing[0]["label"] == "v2"


def test_post_job_definition_rejects_unknown_runtime(api_client):
    """The model accepts any string for runtime_selector; the service
    rejects unknowns and the router turns that into a 400. Keeps the
    catalog schema forward-compatible with new runtimes without
    breaking the API contract.
    """
    payload = JobDefinitionRecord(**_record_kwargs(runtime_selector="not-a-runtime")).model_dump(mode="json")
    resp = api_client.post("/job-definitions", json=payload)
    assert resp.status_code == 400
    assert "Unknown runtime_selector" in resp.text


def test_get_job_definitions_lists_them(api_client):
    api_client.post(
        "/job-definitions",
        json=JobDefinitionRecord(**_record_kwargs(name="a")).model_dump(mode="json"),
    )
    api_client.post(
        "/job-definitions",
        json=JobDefinitionRecord(**_record_kwargs(name="b", runtime_selector="crewai")).model_dump(mode="json"),
    )
    all_rows = api_client.get("/job-definitions").json()
    assert {r["name"] for r in all_rows} == {"a", "b"}

    crewai_only = api_client.get("/job-definitions?runtime_selector=crewai").json()
    assert [r["name"] for r in crewai_only] == ["b"]


def test_get_job_definition_by_name_returns_latest(api_client):
    api_client.post(
        "/job-definitions",
        json=JobDefinitionRecord(**_record_kwargs(version="1.0.0", label="old")).model_dump(mode="json"),
    )
    api_client.post(
        "/job-definitions",
        json=JobDefinitionRecord(**_record_kwargs(version="2.0.0", label="new")).model_dump(mode="json"),
    )
    resp = api_client.get("/job-definitions/by-name/toy")
    assert resp.status_code == 200
    assert resp.json()["version"] == "2.0.0"


def test_get_job_definition_by_name_missing_404s(api_client):
    resp = api_client.get("/job-definitions/by-name/ghost")
    assert resp.status_code == 404


def test_get_job_definition_by_id_404s_if_missing(api_client):
    resp = api_client.get("/job-definitions/toy@99.0.0")
    assert resp.status_code == 404


def test_bundle_helper_posts_to_api(api_client, toy_control: JobControl, monkeypatch):
    """End-to-end: the bundle helper builds + POSTs through real
    httpx machinery (we patch the URL into the api_client fixture's
    TestClient instead of running a real server).
    """
    posted: list[tuple[str, dict]] = []

    def fake_post(url, json=None, timeout=None):  # noqa: ARG001
        path = url.split("/job-definitions", 1)[1] if "/job-definitions" in url else url
        resp = api_client.post(f"/job-definitions{path}", json=json)

        class _R:
            status_code = resp.status_code

            def raise_for_status(self):
                resp.raise_for_status()

            def json(self):
                return resp.json()

        posted.append((url, json))
        return _R()

    import ai_platform.bundle as bundle

    monkeypatch.setattr(bundle.httpx, "post", fake_post)

    out = deploy_job_control(
        toy_control,
        runtime="default",
        code_entrypoint="mathai.toy.execution:register_execution",
        api_url="http://fake",
    )
    assert out.name == "toy"
    assert len(posted) == 1
