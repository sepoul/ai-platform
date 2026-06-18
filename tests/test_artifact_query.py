"""Tests for the PR-3 read-path additions:

- `ArtifactRepository.query` / `ArtifactService.query` — equality filter on
  whitelisted domain fields (PR-3b) + limit/offset pagination (PR-3c).
- `GET /artifacts?...&full=true` — full typed artifacts inline (PR-3a),
  `&<field>=<value>` domain-field filter, `&offset=` pagination.
- `POST /artifacts/batch` — batch hydrate by ids (PR-3d).

Local backend / in-memory, mirroring `test_artifact_listing.py`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_platform.api.routers.artifacts import make_artifacts_router
from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.runtime import registry as deps_mod
from ai_platform.workspace.storage.structured.artifact_repository import (
    LocalArtifactRepository,
)
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig


class _Note(BaseArtifact):
    """Stands in for `note_page` — the FK-grouped type from the friend's
    observation (`source_note_id`)."""
    artifact_type: Literal["note_page"] = "note_page"
    source_note_id: str
    text: str = ""


class _Other(BaseArtifact):
    artifact_type: Literal["other"] = "other"
    value: str = ""


@pytest.fixture
def repo(tmp_path: Path) -> LocalArtifactRepository:
    return LocalArtifactRepository(
        LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts")
    )


@pytest.fixture
def service(repo: LocalArtifactRepository) -> ArtifactService:
    return ArtifactService(repo, registry={"note_page": _Note, "other": _Other})


@pytest.fixture
def client(service: ArtifactService) -> TestClient:
    app = FastAPI()
    app.include_router(make_artifacts_router([_Note, _Other]))
    app.dependency_overrides[deps_mod.get_artifact_service] = lambda: service
    return TestClient(app)


# ---------------------------------------------------------------------------
# Repo.query — field filter + pagination (PR-3b/3c)
# ---------------------------------------------------------------------------


def test_repo_query_filters_by_domain_field(repo, service: ArtifactService):
    for sid, txt in (("A", "p1"), ("B", "p2"), ("A", "p3")):
        service.put(_Note(source_note_id=sid, text=txt))
    out = repo.query(artifact_type="note_page", fields={"source_note_id": "A"})
    assert {p["text"] for p in out} == {"p1", "p3"}


def test_repo_query_pagination_is_disjoint_and_ordered(repo, service: ArtifactService):
    for i in range(5):
        service.put(_Note(source_note_id="A", text=f"t{i}"))
    page1 = repo.query(artifact_type="note_page", limit=2, offset=0)
    page2 = repo.query(artifact_type="note_page", limit=2, offset=2)
    assert len(page1) == 2 and len(page2) == 2
    assert {p["text"] for p in page1}.isdisjoint({p["text"] for p in page2})


# ---------------------------------------------------------------------------
# Service.query — field whitelist (PR-3b safety)
# ---------------------------------------------------------------------------


def test_service_query_allows_declared_field(service: ArtifactService):
    service.put(_Note(source_note_id="A", text="x"))
    out = service.query(artifact_type="note_page", fields={"source_note_id": "A"})
    assert len(out) == 1 and isinstance(out[0], _Note)


def test_service_query_rejects_undeclared_field(service: ArtifactService):
    service.put(_Note(source_note_id="A"))
    with pytest.raises(ValueError):
        service.query(artifact_type="note_page", fields={"not_a_field": "x"})


def test_service_query_rejects_non_identifier_field_name(service: ArtifactService):
    with pytest.raises(ValueError):
        service.query(fields={"payload->>'x'; DROP TABLE artifacts; --": "1"})


# ---------------------------------------------------------------------------
# Router — GET /artifacts filter / full / pagination (PR-3a/3b/3c)
# ---------------------------------------------------------------------------


def test_router_filters_by_domain_field_default_summary(client: TestClient, service):
    service.put(_Note(source_note_id="A", text="keep"))
    service.put(_Note(source_note_id="B", text="drop"))
    body = client.get("/artifacts?artifact_type=note_page&source_note_id=A").json()
    assert body["total"] == 1
    # default page is the cheap summary — no domain fields hydrated.
    assert "source_note_id" not in body["artifacts"][0]


def test_router_full_projection_includes_domain_fields(client: TestClient, service):
    service.put(_Note(source_note_id="A", text="hello"))
    body = client.get("/artifacts?artifact_type=note_page&full=true").json()
    row = body["artifacts"][0]
    assert row["source_note_id"] == "A"
    assert row["text"] == "hello"


def test_router_full_projection_still_filters(client: TestClient, service):
    service.put(_Note(source_note_id="A", text="keep"))
    service.put(_Note(source_note_id="B", text="drop"))
    body = client.get(
        "/artifacts?artifact_type=note_page&source_note_id=A&full=true"
    ).json()
    assert body["total"] == 1
    assert body["artifacts"][0]["text"] == "keep"


def test_router_pagination_offset_is_disjoint(client: TestClient, service):
    for i in range(5):
        service.put(_Note(source_note_id="A", text=f"t{i}"))
    p1 = client.get("/artifacts?artifact_type=note_page&limit=2&offset=0").json()
    p2 = client.get("/artifacts?artifact_type=note_page&limit=2&offset=2").json()
    ids1 = {r["artifact_id"] for r in p1["artifacts"]}
    ids2 = {r["artifact_id"] for r in p2["artifacts"]}
    assert len(ids1) == 2 and len(ids2) == 2 and ids1.isdisjoint(ids2)


def test_router_non_whitelisted_field_is_400(client: TestClient, service):
    service.put(_Note(source_note_id="A"))
    resp = client.get("/artifacts?artifact_type=note_page&bogus_field=1")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Router — POST /artifacts/batch (PR-3d)
# ---------------------------------------------------------------------------


def test_router_batch_hydrates_full_typed_in_order(client: TestClient, service):
    a = _Note(source_note_id="A", text="x")
    b = _Other(value="y")
    service.put(a)
    service.put(b)
    resp = client.post(
        "/artifacts/batch",
        json={"ids": [str(a.artifact_id), str(b.artifact_id)]},
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["artifact_type"] for r in rows] == ["note_page", "other"]
    assert rows[0]["text"] == "x"  # full domain field, not a summary


def test_router_batch_missing_id_404s_whole_batch(client: TestClient, service):
    a = _Note(source_note_id="A")
    service.put(a)
    resp = client.post(
        "/artifacts/batch",
        json={"ids": [str(a.artifact_id), str(uuid4())]},
    )
    assert resp.status_code == 404
