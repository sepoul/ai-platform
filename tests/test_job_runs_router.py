"""
Tests for the platform job-runs router — covers the typed-submit
discriminated union and the legacy fallback when no input type is
registered on a JobDefinition.

No real storage / no LLM. The repo and executor are mocked.
"""
from __future__ import annotations

from typing import Literal, Optional
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from ai_platform.runtime import registry as deps_mod
from ai_platform.api.routers.job_runs import make_job_runs_router
from ai_platform.jobs.execution_policy import (
    ExecutionPolicy,
    JobDefinition,
    NodeGate,
)
from ai_platform.jobs.base_state import BaseJobState
from ai_platform.jobs.graph_execution import GraphCheckpoint
from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.result import BaseJobResult
from ai_platform.workspace.storage.structured.job_repository import JobRecord, JobStatus


# ---------------------------------------------------------------------------
# Dummy state / inputs / results
# ---------------------------------------------------------------------------

class _DummyState(BaseJobState):
    pass


class _DummyResult(BaseJobResult):
    job_type: Literal["dummy"] = "dummy"


class _DummyInput(BaseJobInput):
    job_type: Literal["dummy"] = "dummy"
    question_text: str
    topic: Optional[str] = None
    created_by: Optional[str] = None


class _OtherResult(BaseJobResult):
    job_type: Literal["other"] = "other"


class _OtherInput(BaseJobInput):
    job_type: Literal["other"] = "other"
    payload: str


class _DummyReview(BaseModel):
    approved: bool
    notes: Optional[str] = None


class _OtherReview(BaseModel):
    score: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        extract_result=lambda state: _DummyResult(),
        submit_input_type=_DummyInput,
    )
    base.update(overrides)
    return JobDefinition(**base)


def _make_app(job_defs: list[JobDefinition]) -> tuple[TestClient, MagicMock, MagicMock]:
    fake_executor = MagicMock()
    fake_compute = MagicMock()
    record = JobRecord.create(job_type=job_defs[0].name, graph_ref=job_defs[0].graph_ref)
    fake_executor.submit_graph_job.return_value = record

    deps_mod._job_definitions.clear()
    for jd in job_defs:
        deps_mod._job_definitions[jd.name] = jd

    app = FastAPI()
    app.include_router(make_job_runs_router(deps_mod._job_definitions))
    app.dependency_overrides[deps_mod.get_executor] = lambda: fake_executor
    app.dependency_overrides[deps_mod.get_compute] = lambda: fake_compute
    app.dependency_overrides[deps_mod.get_job_definitions] = lambda: deps_mod._job_definitions
    return TestClient(app), fake_executor, fake_compute


def _wire_pending_review(
    executor: MagicMock,
    job_def: JobDefinition,
    gated_node: str,
) -> JobRecord:
    """Set up a record paused at a gate so /review can resume it."""
    record = JobRecord.create(job_type=job_def.name, graph_ref=job_def.graph_ref)
    record.state.status = JobStatus.WAITING_INPUT
    executor.repo.get.return_value = record
    executor.load_checkpoint.return_value = GraphCheckpoint(
        state_data={},
        next_node_key="__done__",
        gated_node=gated_node,
        attempt=0,
    )
    return record


# ---------------------------------------------------------------------------
# Typed-input tests (single registered input type)
# ---------------------------------------------------------------------------

def test_submit_typed_input_validates_and_dispatches():
    job_def = _base_job_def()
    client, executor, _ = _make_app([job_def])

    resp = client.post(
        "/jobs/runs/submit",
        json={"job_type": "dummy", "question_text": "1+1", "topic": "algebra", "created_by": "u1"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "job_id" in body and "status" in body

    executor.submit_graph_job.assert_called_once()
    kwargs = executor.submit_graph_job.call_args.kwargs
    assert kwargs["job_type"] == "dummy"
    assert kwargs["graph_ref"] == "dummy_graph"
    assert kwargs["deps_payload"] == {
        "question_text": "1+1",
        "topic": "algebra",
        "created_by": "u1",
    }
    assert kwargs["created_by"] == "u1"


def test_submit_typed_input_rejects_missing_required_field():
    client, _, _ = _make_app([_base_job_def()])

    resp = client.post("/jobs/runs/submit", json={"job_type": "dummy", "topic": "algebra"})
    assert resp.status_code == 422
    # Pydantic's error mentions the missing field
    assert "question_text" in resp.text


def test_submit_typed_input_rejects_unknown_field():
    """`extra='forbid'` on BaseJobInput should reject unknown keys."""
    client, _, _ = _make_app([_base_job_def()])

    resp = client.post(
        "/jobs/runs/submit",
        json={"job_type": "dummy", "question_text": "x", "garbage_field": 42},
    )
    assert resp.status_code == 422
    assert "garbage_field" in resp.text


def test_submit_typed_input_rejects_unknown_job_type():
    client, _, _ = _make_app([_base_job_def()])

    # Pydantic rejects at the literal check — wrong job_type means the body
    # does not match the registered input shape.
    resp = client.post("/jobs/runs/submit", json={"job_type": "ghost", "question_text": "x"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Discriminated-union tests (multiple input types)
# ---------------------------------------------------------------------------

def test_submit_discriminated_union_routes_by_job_type():
    dummy = _base_job_def()
    other = _base_job_def(
        name="other",
        graph_ref="other_graph",
        result_type=_OtherResult,
        extract_result=lambda state: _OtherResult(),
        submit_input_type=_OtherInput,
    )
    client, executor, _ = _make_app([dummy, other])

    resp = client.post("/jobs/runs/submit", json={"job_type": "other", "payload": "hello"})
    assert resp.status_code == 200, resp.text
    kwargs = executor.submit_graph_job.call_args.kwargs
    assert kwargs["job_type"] == "other"
    assert kwargs["graph_ref"] == "other_graph"
    assert kwargs["deps_payload"] == {"payload": "hello"}


def test_submit_discriminated_union_rejects_wrong_shape_for_job_type():
    """A `job_type=dummy` body that omits `question_text` must fail even
    though `_OtherInput` exists in the union — the discriminator pins it."""
    dummy = _base_job_def()
    other = _base_job_def(
        name="other",
        graph_ref="other_graph",
        result_type=_OtherResult,
        extract_result=lambda state: _OtherResult(),
        submit_input_type=_OtherInput,
    )
    client, _, _ = _make_app([dummy, other])

    resp = client.post("/jobs/runs/submit", json={"job_type": "dummy", "payload": "wrong"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# OpenAPI surface — TS clients narrow on this
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Typed review tests
# ---------------------------------------------------------------------------

def _gate(node: str = "GateNode", review_type=_DummyReview) -> NodeGate:
    return NodeGate(node_name=node, review_type=review_type)


def test_review_typed_body_resumes_job():
    job_def = _base_job_def(policy=ExecutionPolicy(gates=[_gate()]))
    client, executor, _ = _make_app([job_def])
    record = _wire_pending_review(executor, job_def, "GateNode")

    resp = client.post(
        f"/jobs/{record.spec.job_id}/review",
        json={"approved": True, "notes": "looks good"},
    )
    assert resp.status_code == 200, resp.text
    # Resume token written, status flipped to PENDING.
    executor.repo.put.assert_called_once()
    updated = executor.repo.put.call_args.args[0]
    assert updated.state.status == JobStatus.PENDING
    assert updated.state.resume_token  # non-empty checkpoint json
    assert "looks good" in updated.state.resume_token


def test_review_rejects_missing_required_field():
    job_def = _base_job_def(policy=ExecutionPolicy(gates=[_gate()]))
    client, executor, _ = _make_app([job_def])
    record = _wire_pending_review(executor, job_def, "GateNode")

    resp = client.post(f"/jobs/{record.spec.job_id}/review", json={"notes": "missing approved"})
    assert resp.status_code == 422
    assert "approved" in resp.text


def test_review_rejects_when_no_pending_gate():
    """Even with a valid review body, /review must 409 if the checkpoint
    has no gated_node — the job isn't waiting on anyone."""
    job_def = _base_job_def(policy=ExecutionPolicy(gates=[_gate()]))
    client, executor, _ = _make_app([job_def])
    record = JobRecord.create(job_type=job_def.name, graph_ref=job_def.graph_ref)
    executor.repo.get.return_value = record
    executor.load_checkpoint.return_value = GraphCheckpoint(
        state_data={}, next_node_key="__done__", gated_node=None, attempt=0,
    )

    resp = client.post(f"/jobs/{record.spec.job_id}/review", json={"approved": True})
    assert resp.status_code == 409


def test_review_union_rejects_wrong_shape_for_resolved_gate():
    """With two gates registered (different review types), pydantic might
    parse a body that matches the *other* gate's type. The router must
    re-check it against the resolved gate and 422 the mismatch."""
    dummy = _base_job_def(policy=ExecutionPolicy(gates=[_gate("DummyGate", _DummyReview)]))
    other = _base_job_def(
        name="other",
        graph_ref="other_graph",
        result_type=_OtherResult,
        extract_result=lambda state: _OtherResult(),
        submit_input_type=_OtherInput,
        policy=ExecutionPolicy(gates=[_gate("OtherGate", _OtherReview)]),
    )
    client, executor, _ = _make_app([dummy, other])
    # Pause the *dummy* job at its gate, but POST a body shaped like _OtherReview.
    record = _wire_pending_review(executor, dummy, "DummyGate")

    resp = client.post(f"/jobs/{record.spec.job_id}/review", json={"score": 7})
    assert resp.status_code == 422
    assert "DummyGate" in resp.json()["detail"]


def test_submit_calls_compute_enqueue_with_job_id():
    """The router must hand the job id to the configured ComputeBackend
    so non-poll backends (Celery, in-process thread pool) can deliver it."""
    job_def = _base_job_def()
    client, executor, compute = _make_app([job_def])

    resp = client.post(
        "/jobs/runs/submit",
        json={"job_type": "dummy", "question_text": "x"},
    )
    assert resp.status_code == 200, resp.text

    expected_id = str(executor.submit_graph_job.return_value.spec.job_id)
    compute.enqueue.assert_called_once_with(expected_id)


def test_review_calls_compute_enqueue_to_resume_run():
    """Resuming a paused job is a 'submit moment' too — queue-based
    backends need to re-deliver the job id to a worker."""
    job_def = _base_job_def(policy=ExecutionPolicy(gates=[_gate()]))
    client, executor, compute = _make_app([job_def])
    record = _wire_pending_review(executor, job_def, "GateNode")

    resp = client.post(
        f"/jobs/{record.spec.job_id}/review",
        json={"approved": True, "notes": "ok"},
    )
    assert resp.status_code == 200, resp.text

    compute.enqueue.assert_called_once_with(str(record.spec.job_id))


def test_openapi_uses_typed_review_schema():
    job_def = _base_job_def(policy=ExecutionPolicy(gates=[_gate()]))
    client, _, _ = _make_app([job_def])

    schema = client.app.openapi()
    review = schema["paths"]["/jobs/{job_id}/review"]["post"]["requestBody"]
    body_schema = review["content"]["application/json"]["schema"]
    # Single registered gate → body type is _DummyReview directly.
    assert body_schema["$ref"].endswith("_DummyReview")
    assert "_DummyReview" in schema["components"]["schemas"]


def test_openapi_uses_typed_submit_schema():
    dummy = _base_job_def()
    other = _base_job_def(
        name="other",
        graph_ref="other_graph",
        result_type=_OtherResult,
        extract_result=lambda state: _OtherResult(),
        submit_input_type=_OtherInput,
    )
    client, _, _ = _make_app([dummy, other])

    schema = client.app.openapi()
    assert "_DummyInput" in schema["components"]["schemas"]
    assert "_OtherInput" in schema["components"]["schemas"]
    dummy_schema = schema["components"]["schemas"]["_DummyInput"]
    assert dummy_schema["properties"]["job_type"]["const"] == "dummy"
