"""Workflow descriptor: the offline builder + the API router that serves it.

The descriptor is generated in an engine context and parked in the blob
store; the router only reads + serves it (no pydantic_graph at request time).
"""
from __future__ import annotations

import json
from typing import Literal
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from ai_platform.api.routers import workflows as workflows_mod
from ai_platform.jobs.workflow_descriptor import build_descriptors_map, build_workflow_descriptor
from ai_platform.jobs.execution_policy import (
    EdgeSpec,
    ExecutionPolicy,
    JobControl,
    JobExecution,
    NodeGate,
)
from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.result import BaseJobResult
from ai_platform.runtime import registry as deps_mod
from ai_platform.workspace.storage.exceptions import ObjectNotFound


class _Input(BaseJobInput):
    job_type: Literal["demo"] = "demo"
    question_text: str


class _Result(BaseJobResult):
    job_type: Literal["demo"] = "demo"


class _Review(BaseModel):
    approved: bool


class _NodeA:
    stage_label = "Step A"
    stage_description = "does A"


class _NodeB:
    stage_label = "Step B"  # no description → None


_GATES = [NodeGate("B", _Review)]


def _control() -> JobControl:
    return JobControl(
        name="demo",
        label="demo_graph",
        submit_input_type=_Input,
        result_type=_Result,
        gates=_GATES,
    )


def _execution() -> JobExecution:
    return JobExecution(
        name="demo",
        graph=None,
        state_type=object,
        start_node_key="A",
        node_registry={"A": _NodeA, "B": _NodeB},
        deps_factory=lambda payload: None,
        extract_result=lambda state: _Result(),
        policy=ExecutionPolicy(gates=_GATES),
        edges=[EdgeSpec("A", "B", "to b")],
    )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def test_descriptor_projects_graph_into_spec():
    d = build_workflow_descriptor(_control(), _execution())

    assert d.job_type == "demo"
    assert d.label == "demo_graph"
    assert [s.id for s in d.stages] == ["A", "B"]

    a, b = d.stages
    assert (a.label, a.description, a.is_human_step) == ("Step A", "does A", False)
    assert (b.label, b.description, b.is_human_step) == ("Step B", None, True)
    # The gated stage exposes the review schema as resume params.
    assert [p.name for p in b.resume_params] == ["approved"]

    assert [p.name for p in d.submit_params] == ["question_text"]
    assert (d.edges[0].source, d.edges[0].target, d.edges[0].label) == ("A", "B", "to b")
    assert d.gates[0].node_name == "B"
    assert d.gates[0].review_type == "_Review"


# ---------------------------------------------------------------------------
# Router (serves the parked blob; optional when ungenerated)
# ---------------------------------------------------------------------------

def _client(blob: bytes | None) -> TestClient:
    fake_client = MagicMock()
    if blob is None:
        fake_client.file_repo.get_canonical_file_bytes.side_effect = ObjectNotFound("absent")
    else:
        fake_client.file_repo.get_canonical_file_bytes.return_value = blob

    app = FastAPI()
    app.include_router(workflows_mod.router)
    app.dependency_overrides[deps_mod.get_platform_client] = lambda: fake_client
    return TestClient(app)


def _blob() -> bytes:
    d = build_workflow_descriptor(_control(), _execution())
    return json.dumps({"demo": d.model_dump(mode="json")}).encode("utf-8")


def test_router_lists_from_blob():
    resp = _client(_blob()).get("/workflows")
    assert resp.status_code == 200
    assert resp.json()["workflows"] == [{"job_type": "demo", "label": "demo_graph"}]


def test_router_serves_spec_from_blob():
    resp = _client(_blob()).get("/workflows/demo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_type"] == "demo"
    assert body["stages"][1]["is_human_step"] is True


def test_router_404_unknown_job_type():
    assert _client(_blob()).get("/workflows/ghost").status_code == 404


def test_router_optional_when_ungenerated():
    client = _client(None)
    assert client.get("/workflows").json() == {"workflows": []}
    assert client.get("/workflows/demo").status_code == 404


# ---------------------------------------------------------------------------
# build_descriptors_map — intersection of both planes (issue #56)
# ---------------------------------------------------------------------------

def test_build_descriptors_map_only_emits_job_types_in_both_planes():
    controls = {"demo": _control(), "control_only": _control()}
    executions = {"demo": _execution(), "orphan_exec": _execution()}
    out = build_descriptors_map(controls, executions)
    # Only "demo" is in both planes; the control-only and execution-only
    # entries are skipped (that's what makes the per-runtime split mergeable).
    assert set(out) == {"demo"}
    assert out["demo"]["job_type"] == "demo"
    assert [s["id"] for s in out["demo"]["stages"]] == ["A", "B"]


# ---------------------------------------------------------------------------
# POST /workflows — merge-upsert into the blob (issue #56)
# ---------------------------------------------------------------------------

class _StatefulFileRepo:
    """In-memory canonical-file store so POST→GET round-trips in one test."""

    def __init__(self, initial: bytes | None = None):
        self._blob = initial

    def get_canonical_file_bytes(self, logical_name: str) -> bytes:
        if self._blob is None:
            raise ObjectNotFound(logical_name)
        return self._blob

    def put_canonical_file(self, payload):
        self._blob = payload.bytes_data
        return None


def _rw_client(initial: bytes | None = None) -> TestClient:
    fake = MagicMock()
    fake.file_repo = _StatefulFileRepo(initial)
    app = FastAPI()
    app.include_router(workflows_mod.router)
    app.dependency_overrides[deps_mod.get_platform_client] = lambda: fake
    return TestClient(app)


def _descriptor(job_type: str) -> dict:
    d = build_workflow_descriptor(_control(), _execution()).model_dump(mode="json")
    d["job_type"] = job_type
    return d


def test_push_workflows_creates_blob_then_serves_it():
    client = _rw_client(None)  # nothing generated yet
    resp = client.post("/workflows", json={"workflows": {"demo": _descriptor("demo")}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["job_types"] == ["demo"]
    # Now the GET surface is populated from the same store.
    assert client.get("/workflows").json()["workflows"] == [
        {"job_type": "demo", "label": "demo_graph"}
    ]
    assert client.get("/workflows/demo").status_code == 200


def test_push_workflows_merges_across_runtimes():
    client = _rw_client(None)
    client.post("/workflows", json={"workflows": {"demo": _descriptor("demo")}})
    # A second runtime pushes a different job type — must accumulate, not replace.
    resp = client.post("/workflows", json={"workflows": {"other": _descriptor("other")}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["job_types"] == ["demo", "other"]
    listed = {w["job_type"] for w in client.get("/workflows").json()["workflows"]}
    assert listed == {"demo", "other"}


def test_push_workflows_upserts_existing_job_type():
    client = _rw_client(None)
    client.post("/workflows", json={"workflows": {"demo": _descriptor("demo")}})
    updated = _descriptor("demo")
    updated["label"] = "demo_graph_v2"
    client.post("/workflows", json={"workflows": {"demo": updated}})
    body = client.get("/workflows/demo").json()
    assert body["label"] == "demo_graph_v2"  # replaced, not duplicated
    assert len(client.get("/workflows").json()["workflows"]) == 1
