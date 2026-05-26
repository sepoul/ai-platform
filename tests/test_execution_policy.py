"""
Unit tests for the execution policy framework.

Uses a dummy graph (ComputeNode → SummarizeNode → End) with no external
dependencies — no Anthropic API, no storage, no filesystem.
"""
from __future__ import annotations

import pytest
from dataclasses import dataclass
from typing import Any, Literal, Optional
from unittest.mock import MagicMock
from uuid import uuid4

from pydantic import BaseModel
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from ai_platform.jobs.base_state import BaseJobState
from ai_platform.jobs.execution_policy import (
    ExecutionPolicy,
    JobExecution,
    NodeGate,
)
from ai_platform.jobs.graph_execution import GraphCheckpoint
from ai_platform.jobs.job_runner import SENTINEL_DONE, run_graph_job
from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.result import BaseJobResult


# ---------------------------------------------------------------------------
# Dummy graph: ComputeNode → SummarizeNode → End
# No external I/O — safe for unit tests.
# ---------------------------------------------------------------------------

class DummyState(BaseJobState):
    computed_value: Optional[int] = None
    summary: Optional[str] = None


@dataclass
class ComputeNode(BaseNode[DummyState, None]):
    stage_label = "Compute"
    stage_description = "Produces computed_value = 42"

    async def run(self, ctx: GraphRunContext[DummyState, None]) -> "SummarizeNode":
        ctx.state.computed_value = 42
        return SummarizeNode()


@dataclass
class SummarizeNode(BaseNode[DummyState, None]):
    stage_label = "Summarize"
    stage_description = "Produces summary string"

    async def run(self, ctx: GraphRunContext[DummyState, None]) -> End[None]:
        ctx.state.summary = f"Value is {ctx.state.computed_value}"
        return End(None)


dummy_graph = Graph(nodes=(ComputeNode, SummarizeNode), state_type=DummyState)

dummy_node_registry = {
    "ComputeNode": ComputeNode,
    "SummarizeNode": SummarizeNode,
}


# ---------------------------------------------------------------------------
# Dummy review type
# ---------------------------------------------------------------------------

class SummarizeReview(BaseModel):
    approved: bool
    notes: str


# ---------------------------------------------------------------------------
# Dummy typed result
# ---------------------------------------------------------------------------

class DummyResult(BaseJobResult):
    job_type: Literal["dummy"] = "dummy"
    computed_value: Optional[int] = None
    review: Optional[SummarizeReview] = None


class DummyInput(BaseJobInput):
    job_type: Literal["dummy"] = "dummy"


# ---------------------------------------------------------------------------
# Dummy executor (in-memory, no storage)
# ---------------------------------------------------------------------------

class MockExecutor:
    def __init__(self, checkpoint: GraphCheckpoint | None = None):
        self._checkpoint = checkpoint
        self.saved_checkpoint: GraphCheckpoint | None = None
        self.completed = False
        self.completed_result: dict | None = None
        self.failed = False
        self.progress: list[str] = []

    # Minimal interface required by run_graph_job
    def load_checkpoint(self, job_id: str) -> GraphCheckpoint | None:
        return self._checkpoint

    def save_checkpoint(self, job_id, state, next_node_key, reason=None, gated_node=None):
        self.saved_checkpoint = GraphCheckpoint(
            state_data=state, next_node_key=next_node_key, gated_node=gated_node
        )

    def complete_job(self, job_id, result=None):
        self.completed = True
        self.completed_result = result

    def fail_job(self, job_id, error, retryable=False):
        self.failed = True

    def update_progress(self, job_id, stage=None, percent=None, message=None):
        if stage:
            self.progress.append(stage)


def _make_record(job_type: str = "dummy") -> Any:
    record = MagicMock()
    record.spec.job_id = uuid4()
    record.spec.job_type = job_type
    record.spec.input_payload = {"deps": {}}
    return record


def _make_job_def(policy: ExecutionPolicy) -> JobExecution:
    def _extract(state: DummyState) -> DummyResult:
        review_raw = state.node_reviews.get("SummarizeNode")
        review = SummarizeReview.model_validate(review_raw) if review_raw else None
        return DummyResult(computed_value=state.computed_value, review=review)

    return JobExecution(
        name="dummy",
        graph=dummy_graph,
        state_type=DummyState,
        start_node_key="ComputeNode",
        node_registry=dummy_node_registry,
        deps_factory=lambda payload: None,
        extract_result=_extract,
        policy=policy,
    )


# ---------------------------------------------------------------------------
# BaseJobState tests
# ---------------------------------------------------------------------------

def test_has_review_false_initially():
    state = DummyState()
    assert state.has_review("SummarizeNode") is False


def test_set_and_get_review():
    state = DummyState()
    review = SummarizeReview(approved=True, notes="looks good")
    state.set_review("SummarizeNode", review)

    assert state.has_review("SummarizeNode") is True
    recovered = state.get_review("SummarizeNode", SummarizeReview)
    assert recovered is not None
    assert recovered.approved is True
    assert recovered.notes == "looks good"


def test_get_review_returns_none_for_missing():
    state = DummyState()
    assert state.get_review("NonExistent", SummarizeReview) is None


def test_node_reviews_survives_round_trip():
    """Checkpoint serialisation: model_dump → model_validate must preserve reviews."""
    state = DummyState(computed_value=7)
    state.set_review("SummarizeNode", SummarizeReview(approved=False, notes="nope"))

    raw = state.model_dump()
    restored = DummyState.model_validate(raw)

    assert restored.computed_value == 7
    assert restored.has_review("SummarizeNode")
    r = restored.get_review("SummarizeNode", SummarizeReview)
    assert r is not None and r.approved is False


# ---------------------------------------------------------------------------
# NodeGate / ExecutionPolicy tests
# ---------------------------------------------------------------------------

def test_policy_gate_for_returns_correct_gate():
    gate = NodeGate("SummarizeNode", SummarizeReview)
    policy = ExecutionPolicy(gates=[gate])

    assert policy.gate_for("SummarizeNode") is gate
    assert policy.gate_for("ComputeNode") is None
    assert policy.gate_for("Unknown") is None


def test_policy_validate_passes_when_nodes_exist():
    policy = ExecutionPolicy(gates=[
        NodeGate("SummarizeNode", SummarizeReview),
    ])
    policy.validate(dummy_graph)   # must not raise


def test_policy_validate_fails_for_unknown_node():
    policy = ExecutionPolicy(gates=[
        NodeGate("NonExistentNode", SummarizeReview),
    ])
    with pytest.raises(ValueError, match="NonExistentNode"):
        policy.validate(dummy_graph)


def test_policy_validate_fails_for_each_unknown_node():
    policy = ExecutionPolicy(gates=[
        NodeGate("GhostNode", SummarizeReview),
    ])
    with pytest.raises(ValueError, match="GhostNode"):
        policy.validate(dummy_graph)


# ---------------------------------------------------------------------------
# Generic handler integration tests (no I/O, no LLM)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_handler_no_gate_completes_directly():
    """With an empty policy, the graph runs fully and completes without pausing."""
    policy = ExecutionPolicy(gates=[])
    job_def = _make_job_def(policy)
    executor = MockExecutor()
    record = _make_record()

    await run_graph_job(record, executor, job_def)

    assert executor.completed is True
    assert executor.saved_checkpoint is None
    assert executor.completed_result == {
        "artifact_refs": [],
        "job_type": "dummy",
        "computed_value": 42,
        "review": None,
    }


@pytest.mark.anyio
async def test_handler_gate_on_summarize_pauses():
    """Policy gate on SummarizeNode: handler pauses after SummarizeNode runs."""
    policy = ExecutionPolicy(gates=[
        NodeGate("SummarizeNode", SummarizeReview),
    ])
    job_def = _make_job_def(policy)
    executor = MockExecutor()
    record = _make_record()

    await run_graph_job(record, executor, job_def)

    assert executor.completed is False
    assert executor.saved_checkpoint is not None
    ckpt = executor.saved_checkpoint
    assert ckpt.next_node_key == SENTINEL_DONE   # graph is done computing
    assert ckpt.gated_node == "SummarizeNode"
    state = DummyState.model_validate(ckpt.state_data)
    assert state.computed_value == 42
    assert state.summary == "Value is 42"
    assert not state.has_review("SummarizeNode")


@pytest.mark.anyio
async def test_handler_gate_on_compute_pauses_before_summarize():
    """Policy gate on ComputeNode: handler pauses and next_node_key points to SummarizeNode."""
    policy = ExecutionPolicy(gates=[
        NodeGate("ComputeNode", SummarizeReview),
    ])
    job_def = _make_job_def(policy)
    executor = MockExecutor()
    record = _make_record()

    await run_graph_job(record, executor, job_def)

    assert executor.completed is False
    ckpt = executor.saved_checkpoint
    assert ckpt is not None
    assert ckpt.next_node_key == "SummarizeNode"   # SummarizeNode hasn't run yet
    assert ckpt.gated_node == "ComputeNode"


@pytest.mark.anyio
async def test_handler_resume_with_review_completes():
    """Resume path: review is in state → SENTINEL_DONE → complete_job called."""
    policy = ExecutionPolicy(gates=[
        NodeGate("SummarizeNode", SummarizeReview),
    ])
    job_def = _make_job_def(policy)

    # Simulate the state after the first run (SummarizeNode has run, review not yet given)
    state_after_run = DummyState(computed_value=42, summary="Value is 42")
    state_after_run.set_review(
        "SummarizeNode", SummarizeReview(approved=True, notes="accepted")
    )

    checkpoint = GraphCheckpoint(
        state_data=state_after_run.model_dump(),
        next_node_key=SENTINEL_DONE,
        gated_node=None,   # review already injected by the review endpoint
    )
    executor = MockExecutor(checkpoint=checkpoint)
    record = _make_record()

    await run_graph_job(record, executor, job_def)

    assert executor.completed is True
    result = executor.completed_result
    assert result is not None
    assert result["computed_value"] == 42
    assert result["review"]["approved"] is True


@pytest.mark.anyio
async def test_handler_applies_pending_review_on_resume():
    """Review-as-data: the API parked a raw review payload on the record; the
    worker merges it into state on resume, clears it, persists, and completes."""
    policy = ExecutionPolicy(gates=[NodeGate("SummarizeNode", SummarizeReview)])
    job_def = _make_job_def(policy)

    # State after the first run — SummarizeNode ran, but NO review in state yet
    # and the checkpoint is still gated on it (unlike the pre-merged case above).
    state_after_run = DummyState(computed_value=42, summary="Value is 42")
    checkpoint = GraphCheckpoint(
        state_data=state_after_run.model_dump(),
        next_node_key=SENTINEL_DONE,
        gated_node="SummarizeNode",
    )
    executor = MockExecutor(checkpoint=checkpoint)
    executor.repo = MagicMock()

    record = _make_record()
    record.state.pending_review = {"approved": True, "notes": "accepted"}

    await run_graph_job(record, executor, job_def)

    assert executor.completed is True
    assert executor.completed_result["review"]["approved"] is True
    # The worker cleared the parked review and persisted the record.
    assert record.state.pending_review is None
    executor.repo.put.assert_called_once_with(record)


@pytest.mark.anyio
async def test_handler_resume_from_mid_graph_gate():
    """Resume from ComputeNode gate: SummarizeNode runs, then job completes (no gate on it)."""
    policy = ExecutionPolicy(gates=[
        NodeGate("ComputeNode", SummarizeReview),
    ])
    job_def = _make_job_def(policy)

    # After first run: ComputeNode ran, review injected into state
    state_with_review = DummyState(computed_value=42)
    state_with_review.set_review(
        "ComputeNode", SummarizeReview(approved=True, notes="compute ok")
    )

    checkpoint = GraphCheckpoint(
        state_data=state_with_review.model_dump(),
        next_node_key="SummarizeNode",   # resume here
        gated_node=None,
    )
    executor = MockExecutor(checkpoint=checkpoint)
    record = _make_record()

    await run_graph_job(record, executor, job_def)

    # SummarizeNode ran; no gate on it → complete directly
    assert executor.completed is True
    result = executor.completed_result
    assert result is not None
    assert result["computed_value"] == 42
    assert result["review"] is None   # no gate on SummarizeNode in this policy


@pytest.mark.anyio
async def test_handler_unknown_checkpoint_node_fails_job():
    """Checkpoint references a node not in registry → fail_job called."""
    policy = ExecutionPolicy(gates=[])
    job_def = _make_job_def(policy)

    checkpoint = GraphCheckpoint(
        state_data=DummyState().model_dump(),
        next_node_key="GhostNode",
    )
    executor = MockExecutor(checkpoint=checkpoint)
    record = _make_record()

    await run_graph_job(record, executor, job_def)

    assert executor.failed is True
    assert executor.completed is False
