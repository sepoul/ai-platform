"""
Tests for the platform jobs router — covers the typed-result discriminated
union and the workspace-backed `fetch_result` fallback behavior.

No real storage / no LLM. The repo and workspace are mocked.
"""
from __future__ import annotations

from typing import Literal, Optional
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from ai_platform.runtime import registry as deps_mod
from ai_platform.api.routers.jobs import make_jobs_router
from ai_platform.jobs.execution_policy import (
    ExecutionPolicy,
    JobDefinition,
)
from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.result import BaseJobResult
from ai_platform.workspace.storage.structured.job_repository import (
    JobRecord,
    JobStatus,
)


# ---------------------------------------------------------------------------
# Dummy state + result
# ---------------------------------------------------------------------------

class _DummyState(BaseModel):
    value: Optional[int] = None


class _DummyResult(BaseJobResult):
    job_type: Literal["dummy"] = "dummy"
    value: Optional[int] = None
    source: Optional[str] = None  # "payload" or "workspace" — to prove which branch ran


class _DummyInput(BaseJobInput):
    job_type: Literal["dummy"] = "dummy"


def _make_record(status: JobStatus, payload: dict | None = None) -> JobRecord:
    record = JobRecord.create(job_type="dummy", graph_ref="dummy_graph")
    record.state.status = status
    record.state.result_payload = payload
    return record


def _make_app(job_def: JobDefinition, record: JobRecord) -> TestClient:
    """Wire a FastAPI app with the jobs router and dependency overrides."""
    fake_executor = MagicMock()
    fake_executor.repo.get.return_value = record

    # Reset and register only this job def
    deps_mod._job_definitions.clear()
    deps_mod._job_definitions[job_def.name] = job_def

    app = FastAPI()
    app.include_router(make_jobs_router(deps_mod._job_definitions))
    app.dependency_overrides[deps_mod.get_executor] = lambda: fake_executor
    app.dependency_overrides[deps_mod.get_job_definitions] = lambda: deps_mod._job_definitions
    return TestClient(app)


def _base_job_def(**overrides) -> JobDefinition:
    base = dict(
        name="dummy",
        graph_ref="dummy_graph",
        graph=None,
        state_type=_DummyState,
        start_node_key="N",
        node_registry={},
        deps_factory=lambda payload: None,
        policy=ExecutionPolicy(gates=[]),
        result_type=_DummyResult,
        extract_result=lambda state: _DummyResult(value=state.value, source="payload"),
        submit_input_type=_DummyInput,
    )
    base.update(overrides)
    return JobDefinition(**base)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_result_endpoint_uses_payload_when_no_fetcher():
    job_def = _base_job_def()  # no fetch_result
    record = _make_record(
        JobStatus.SUCCEEDED,
        payload={"job_type": "dummy", "value": 42, "source": "payload"},
    )
    client = _make_app(job_def, record)

    resp = client.get(f"/jobs/{record.spec.job_id}/result")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_id"] == str(record.spec.job_id)
    assert body["result"] == {
        "artifact_refs": [],
        "job_type": "dummy",
        "value": 42,
        "source": "payload",
    }


def test_result_endpoint_uses_fetcher_when_present():
    """When `fetch_result` is defined, the endpoint resolves the canonical
    artifact via the workspace, ignoring `result_payload`."""

    def _fetch(record) -> _DummyResult:
        return _DummyResult(value=99, source="workspace")

    job_def = _base_job_def(fetch_result=_fetch)
    # Payload says value=1 (stale preview). Fetcher should win.
    record = _make_record(
        JobStatus.SUCCEEDED,
        payload={"job_type": "dummy", "value": 1, "source": "payload"},
    )
    client = _make_app(job_def, record)

    resp = client.get(f"/jobs/{record.spec.job_id}/result")
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"] == {
        "artifact_refs": [],
        "job_type": "dummy",
        "value": 99,
        "source": "workspace",
    }


def test_result_endpoint_returns_404_when_fetcher_raises():
    def _fetch(record):
        raise RuntimeError("artifact missing")

    job_def = _base_job_def(fetch_result=_fetch)
    record = _make_record(JobStatus.SUCCEEDED, payload=None)
    client = _make_app(job_def, record)

    resp = client.get(f"/jobs/{record.spec.job_id}/result")
    assert resp.status_code == 404
    assert "artifact missing" in resp.json()["detail"]


def test_result_endpoint_409_when_job_not_terminal():
    job_def = _base_job_def()
    record = _make_record(JobStatus.RUNNING, payload=None)
    client = _make_app(job_def, record)

    resp = client.get(f"/jobs/{record.spec.job_id}/result")
    assert resp.status_code == 409


def test_status_endpoint_serves_payload_preview_not_fetcher():
    """Status endpoint must remain cheap — it should not invoke the fetcher
    even when one is defined; it only validates the in-record payload."""

    def _fetch(record):
        raise AssertionError("fetcher must not be called from status endpoint")

    job_def = _base_job_def(fetch_result=_fetch)
    record = _make_record(
        JobStatus.SUCCEEDED,
        payload={"job_type": "dummy", "value": 7, "source": "payload"},
    )
    client = _make_app(job_def, record)

    resp = client.get(f"/jobs/{record.spec.job_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "SUCCEEDED"
    assert body["result"] == {
        "artifact_refs": [],
        "job_type": "dummy",
        "value": 7,
        "source": "payload",
    }


def test_openapi_uses_typed_result_schema():
    """Sanity check: OpenAPI exposes the JobResultResponse with a typed result
    referencing the registered _DummyResult — that's what TS clients narrow on."""
    job_def = _base_job_def()
    record = _make_record(JobStatus.SUCCEEDED, payload=None)
    client = _make_app(job_def, record)

    schema = client.app.openapi()
    jrr = schema["components"]["schemas"]["JobResultResponse"]
    # Must reference _DummyResult somewhere under the result property
    assert "_DummyResult" in str(jrr) or "DummyResult" in str(jrr)
    dummy = schema["components"]["schemas"]["_DummyResult"]
    assert dummy["properties"]["job_type"]["const"] == "dummy"
