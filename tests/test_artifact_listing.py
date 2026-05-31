"""Tests for the batched artifact-listing methods.

The repo + service surface gained `list_all` / `list_by_type` /
`list_by_job` to kill the N+1 in `GET /artifacts` (used to
`list_ids()` + `get(id)` per row; on Supabase that meant one
round-trip per artifact). These tests cover the local backend's
in-memory implementation; Supabase parity is exercised by the
integration suite and verified in production.

Three cuts:
1. **Repo level** — raw payload dicts, ordering, filters, limit.
2. **Service level** — typed BaseArtifact hydration, unknown-type
   resilience.
3. **Router level** — `GET /artifacts` end-to-end with each filter.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.workspace.storage.structured.artifact_repository import LocalArtifactRepository
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _TypeA(BaseArtifact):
    artifact_type: Literal["type_a"] = "type_a"
    value: str


class _TypeB(BaseArtifact):
    artifact_type: Literal["type_b"] = "type_b"
    score: float = 0.0


@pytest.fixture
def repo(tmp_path: Path) -> LocalArtifactRepository:
    return LocalArtifactRepository(LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts"))


@pytest.fixture
def service(repo: LocalArtifactRepository) -> ArtifactService:
    return ArtifactService(repo, registry={"type_a": _TypeA, "type_b": _TypeB})


# ---------------------------------------------------------------------------
# Repo — raw-payload list_*
# ---------------------------------------------------------------------------

def test_list_all_returns_empty_when_store_is_empty(repo):
    assert repo.list_all() == []


def test_list_all_returns_payloads_newest_first(repo, service: ArtifactService):
    """`list_all` orders by `created_at` desc — matches Supabase's
    ORDER BY so the frontend index renders newest-first regardless of
    backend.
    """
    a1 = _TypeA(value="first")
    a2 = _TypeA(value="second")
    a3 = _TypeB(score=1.0)
    # Putting in insertion order; `created_at` defaults to wall-clock,
    # so a3 (last) is newest.
    for art in (a1, a2, a3):
        service.put(art)

    payloads = repo.list_all()
    assert len(payloads) == 3
    # Newest first — by created_at, not insertion. a3 was put last.
    assert payloads[0]["artifact_type"] == "type_b"


def test_list_all_respects_limit(repo, service: ArtifactService):
    for i in range(5):
        service.put(_TypeA(value=f"v{i}"))
    assert len(repo.list_all(limit=3)) == 3
    assert len(repo.list_all()) == 5


def test_list_by_type_filters_to_one_discriminator(repo, service: ArtifactService):
    service.put(_TypeA(value="a"))
    service.put(_TypeB(score=2.0))
    service.put(_TypeA(value="b"))
    assert {p["value"] for p in repo.list_by_type("type_a")} == {"a", "b"}
    assert len(repo.list_by_type("type_b")) == 1


def test_list_by_type_limit_applies_after_filter(repo, service: ArtifactService):
    for i in range(4):
        service.put(_TypeA(value=f"a{i}"))
    service.put(_TypeB(score=1.0))
    assert len(repo.list_by_type("type_a", limit=2)) == 2


def test_list_by_type_unknown_type_returns_empty(repo, service: ArtifactService):
    service.put(_TypeA(value="x"))
    assert repo.list_by_type("nonexistent") == []


def test_list_by_job_filters_by_created_by_job(repo, service: ArtifactService):
    jid = str(uuid4())
    other = str(uuid4())
    service.put(_TypeA(value="mine", created_by_job=jid))
    service.put(_TypeA(value="theirs", created_by_job=other))
    service.put(_TypeA(value="orphan"))  # no created_by_job
    rows = repo.list_by_job(jid)
    assert len(rows) == 1
    assert rows[0]["value"] == "mine"


def test_list_by_job_accepts_uuid_or_str(repo, service: ArtifactService):
    jid_uuid = uuid4()
    service.put(_TypeA(value="x", created_by_job=str(jid_uuid)))
    # Service does the str() coercion; both call shapes work.
    assert len(repo.list_by_job(str(jid_uuid))) == 1


# ---------------------------------------------------------------------------
# Repo + Service — get_many batching
# ---------------------------------------------------------------------------

def test_repo_get_many_empty_input_returns_empty(repo):
    assert repo.get_many([]) == []


def test_repo_get_many_returns_existing_skips_missing(repo, service: ArtifactService):
    """Repo layer silently drops missing ids — the service is what
    raises on count mismatch (preserves the prior fail-loud contract
    at one consistent layer).
    """
    a = _TypeA(value="hello")
    service.put(a)
    payloads = repo.get_many([str(a.artifact_id), "nonexistent-id"])
    assert len(payloads) == 1
    assert payloads[0]["value"] == "hello"


def test_service_get_many_collapses_to_one_round_trip(service: ArtifactService):
    """End-to-end happy path — gets typed BaseArtifact back, single
    repo call regardless of how many ids."""
    a = _TypeA(value="a")
    b = _TypeB(score=2.0)
    service.put(a)
    service.put(b)
    items = service.get_many([a.artifact_id, b.artifact_id])
    assert {x.artifact_type for x in items} == {"type_a", "type_b"}


def test_service_get_many_preserves_input_order(service: ArtifactService):
    """Locked-in contract from the prior implementation: callers may
    rely on `out[i].artifact_id == ids[i]`. Batched DB queries don't
    guarantee order, so the service re-indexes by id and re-emits in
    input order.
    """
    a = _TypeA(value="a")
    b = _TypeA(value="b")
    c = _TypeA(value="c")
    for art in (a, b, c):
        service.put(art)
    out = service.get_many([c.artifact_id, a.artifact_id, b.artifact_id])
    assert [x.value for x in out] == ["c", "a", "b"]


def test_service_get_many_raises_on_missing_listing_all_missing(service: ArtifactService):
    """The ObjectNotFound message lists every missing id so callers
    can surface a useful error (was implicit in the per-id loop: first
    missing id raised; now we report them all in one go).
    """
    from ai_platform.workspace.storage.exceptions import ObjectNotFound

    a = _TypeA(value="exists")
    service.put(a)
    missing_id = str(uuid4())
    other_missing = str(uuid4())
    with pytest.raises(ObjectNotFound) as exc:
        service.get_many([a.artifact_id, missing_id, other_missing])
    assert missing_id in str(exc.value)
    assert other_missing in str(exc.value)


def test_service_get_many_empty_input_returns_empty(service: ArtifactService):
    assert service.get_many([]) == []


def test_service_get_many_accepts_uuid_or_str(service: ArtifactService):
    a = _TypeA(value="x")
    service.put(a)
    # Mixed UUID + str inputs — service does the str() coercion.
    out = service.get_many([a.artifact_id, str(a.artifact_id)])
    assert len(out) == 2  # same id twice; both resolve


# ---------------------------------------------------------------------------
# Service — typed hydration + unknown-type resilience
# ---------------------------------------------------------------------------

def test_service_list_all_hydrates_to_basemodel(service: ArtifactService):
    service.put(_TypeA(value="hello"))
    service.put(_TypeB(score=3.14))
    items = service.list_all()
    assert len(items) == 2
    assert all(isinstance(a, BaseArtifact) for a in items)


def test_service_list_by_type_returns_typed_subclass(service: ArtifactService):
    service.put(_TypeA(value="x"))
    service.put(_TypeB(score=1.0))
    a_only = service.list_by_type("type_a")
    assert len(a_only) == 1
    assert isinstance(a_only[0], _TypeA)


def test_service_list_by_job_collapses_to_one_round_trip(service: ArtifactService):
    """The whole point of the fix: callers go from O(N) round-trips to
    one. The service should expose `list_by_job` as a first-class
    method, not require `list_all` + filter in Python.
    """
    jid = str(uuid4())
    service.put(_TypeA(value="a", created_by_job=jid))
    service.put(_TypeB(score=2.0, created_by_job=jid))
    service.put(_TypeA(value="other", created_by_job=str(uuid4())))
    items = service.list_by_job(jid)
    assert len(items) == 2
    assert {a.artifact_type for a in items} == {"type_a", "type_b"}


def test_service_skips_unknown_artifact_types_in_list(repo, service: ArtifactService):
    """When a domain is unregistered after rows were written, the
    service must skip them rather than raise — preserves the router's
    prior resilience contract.
    """
    service.put(_TypeA(value="known"))
    # Smuggle a payload with an unregistered type directly into the repo.
    repo.put(str(uuid4()), {
        "artifact_id": str(uuid4()),
        "artifact_type": "ghost",
        "created_at": "2026-05-30T00:00:00Z",
    })
    items = service.list_all()
    assert len(items) == 1
    assert items[0].artifact_type == "type_a"


# ---------------------------------------------------------------------------
# Router — GET /artifacts uses the batched path
# ---------------------------------------------------------------------------

def test_router_list_all_no_filter(repo, service: ArtifactService):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_platform.api.routers.artifacts import make_artifacts_router
    from ai_platform.runtime import registry as deps_mod

    service.put(_TypeA(value="x"))
    service.put(_TypeB(score=1.0))

    app = FastAPI()
    app.include_router(make_artifacts_router([_TypeA, _TypeB]))
    app.dependency_overrides[deps_mod.get_artifact_service] = lambda: service
    client = TestClient(app)

    resp = client.get("/artifacts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    types = {row["artifact_type"] for row in body["artifacts"]}
    assert types == {"type_a", "type_b"}


def test_router_list_by_type_filter(repo, service: ArtifactService):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_platform.api.routers.artifacts import make_artifacts_router
    from ai_platform.runtime import registry as deps_mod

    service.put(_TypeA(value="x"))
    service.put(_TypeB(score=1.0))
    service.put(_TypeA(value="y"))

    app = FastAPI()
    app.include_router(make_artifacts_router([_TypeA, _TypeB]))
    app.dependency_overrides[deps_mod.get_artifact_service] = lambda: service
    client = TestClient(app)

    resp = client.get("/artifacts?artifact_type=type_a")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert all(row["artifact_type"] == "type_a" for row in body["artifacts"])


def test_router_list_by_job_filter(repo, service: ArtifactService):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_platform.api.routers.artifacts import make_artifacts_router
    from ai_platform.runtime import registry as deps_mod

    jid = str(uuid4())
    service.put(_TypeA(value="mine", created_by_job=jid))
    service.put(_TypeA(value="not mine", created_by_job=str(uuid4())))

    app = FastAPI()
    app.include_router(make_artifacts_router([_TypeA, _TypeB]))
    app.dependency_overrides[deps_mod.get_artifact_service] = lambda: service
    client = TestClient(app)

    resp = client.get(f"/artifacts?job_id={jid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["artifacts"][0]["created_by_job"] == jid


def test_router_limit_caps_results(repo, service: ArtifactService):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_platform.api.routers.artifacts import make_artifacts_router
    from ai_platform.runtime import registry as deps_mod

    for i in range(5):
        service.put(_TypeA(value=f"v{i}"))

    app = FastAPI()
    app.include_router(make_artifacts_router([_TypeA, _TypeB]))
    app.dependency_overrides[deps_mod.get_artifact_service] = lambda: service
    client = TestClient(app)

    resp = client.get("/artifacts?limit=3")
    assert resp.status_code == 200
    assert resp.json()["total"] == 3
