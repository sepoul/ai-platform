"""Tests covering artifact-as-output behaviour.

- ArtifactService hydrates by `artifact_type` registry.
- Persistence callback returns IDs; job_runner appends them to state.
- Math QA fetch_result rebuilds the typed result from artifacts.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pytest

from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.jobs.execution_policy import (
    ExecutionPolicy,
    JobExecution,
    PersistencePolicy,
)
from ai_platform.jobs.job_runner import run_graph_job
from ai_platform.jobs.graph_execution import GraphCheckpoint
from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.result import BaseJobResult
from ai_platform.workspace.storage.structured.artifact_repository import LocalArtifactRepository
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig
from typing import Literal


# ---------------------------------------------------------------------------
# Fixture artifact + state
# ---------------------------------------------------------------------------

class _ToyArtifact(BaseArtifact):
    artifact_type: Literal["toy"] = "toy"
    label: str


@pytest.fixture
def artifact_api(tmp_path: Path) -> ArtifactService:
    repo = LocalArtifactRepository(LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts"))
    return ArtifactService(repo, registry={"toy": _ToyArtifact})


# ---------------------------------------------------------------------------
# ArtifactService roundtrip
# ---------------------------------------------------------------------------

def test_put_and_get_artifact_roundtrip(artifact_api: ArtifactService):
    artifact = _ToyArtifact(label="hello")
    artifact_id = artifact_api.put(artifact)

    fetched = artifact_api.get(artifact_id)
    assert isinstance(fetched, _ToyArtifact)
    assert fetched.artifact_id == artifact_id
    assert fetched.label == "hello"


def test_get_many_preserves_order(artifact_api: ArtifactService):
    a = _ToyArtifact(label="a")
    b = _ToyArtifact(label="b")
    artifact_api.put(a)
    artifact_api.put(b)

    out = artifact_api.get_many([b.artifact_id, a.artifact_id])
    assert [x.label for x in out] == ["b", "a"]


def test_get_unknown_type_raises(tmp_path: Path):
    repo = LocalArtifactRepository(LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts"))
    api = ArtifactService(repo, registry={})  # empty registry
    api.repo.put(
        "abc",
        {"artifact_id": "00000000-0000-0000-0000-000000000001", "artifact_type": "ghost"},
    )
    with pytest.raises(ValueError, match="ghost"):
        api.get("abc")


# ---------------------------------------------------------------------------
# job_runner appends minted IDs onto state.artifact_refs
# ---------------------------------------------------------------------------

from dataclasses import dataclass
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from ai_platform.jobs.base_state import BaseJobState


class _SimpleState(BaseJobState):
    value: Optional[int] = None


@dataclass
class _SimpleNode(BaseNode[_SimpleState, None]):
    async def run(self, ctx: GraphRunContext[_SimpleState, None]) -> End[None]:
        ctx.state.value = 1
        return End(None)


_simple_graph = Graph(nodes=(_SimpleNode,), state_type=_SimpleState)


class _SimpleResult(BaseJobResult):
    job_type: Literal["simple"] = "simple"
    value: Optional[int] = None


class _SimpleInput(BaseJobInput):
    job_type: Literal["simple"] = "simple"


def _make_job_def(persist_returns: list[UUID]) -> JobExecution:
    return JobExecution(
        name="simple",
        graph=_simple_graph,
        state_type=_SimpleState,
        start_node_key="_SimpleNode",
        node_registry={"_SimpleNode": _SimpleNode},
        deps_factory=lambda payload: None,
        policy=ExecutionPolicy(gates=[]),
        extract_result=lambda state: _SimpleResult(
            value=state.value, artifact_refs=list(state.artifact_refs)
        ),
        persistence=PersistencePolicy(
            on_complete=lambda job_id, state: list(persist_returns),
        ),
    )


class _CapturingExecutor:
    def __init__(self, checkpoint: GraphCheckpoint | None = None):
        self._checkpoint = checkpoint
        self.completed_result: dict | None = None
        self.completed = False
        self.failed = False
        self.saved_checkpoint: GraphCheckpoint | None = None

    def load_checkpoint(self, job_id):
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

    def update_progress(self, *args, **kwargs):
        pass


def _make_record():
    from unittest.mock import MagicMock
    record = MagicMock()
    record.spec.job_id = uuid4()
    record.spec.job_type = "simple"
    record.spec.input_payload = {"deps": {}}
    return record


@pytest.mark.anyio
async def test_handler_appends_minted_ids_to_state():
    minted = [uuid4(), uuid4()]
    job_def = _make_job_def(persist_returns=minted)
    executor = _CapturingExecutor()
    record = _make_record()

    await run_graph_job(record, executor, job_def)

    assert executor.completed
    assert executor.completed_result is not None
    refs = executor.completed_result["artifact_refs"]
    assert [str(r) for r in refs] == [str(m) for m in minted]


@pytest.mark.anyio
async def test_handler_propagates_persist_exceptions():
    """Persist callback raising must surface — silent failures lead to
    `fetch_result` 404s on a 'SUCCEEDED' job. The outer worker loop is
    responsible for catching this and marking the job FAILED."""
    job_def = JobExecution(
        name="simple",
        graph=_simple_graph,
        state_type=_SimpleState,
        start_node_key="_SimpleNode",
        node_registry={"_SimpleNode": _SimpleNode},
        deps_factory=lambda payload: None,
        policy=ExecutionPolicy(gates=[]),
        extract_result=lambda state: _SimpleResult(
            value=state.value, artifact_refs=list(state.artifact_refs)
        ),
        persistence=PersistencePolicy(
            on_complete=lambda job_id, state: (_ for _ in ()).throw(RuntimeError("boom")),
        ),
    )
    executor = _CapturingExecutor()
    with pytest.raises(RuntimeError, match="boom"):
        await run_graph_job(_make_record(), executor, job_def)
    assert not executor.completed


# ---------------------------------------------------------------------------
# Math QA: end-to-end persist + fetch_result through artifacts
# ---------------------------------------------------------------------------

def test_math_qa_persist_mints_three_artifacts(tmp_path: Path):
    """on_complete called with state holding question + ai_response + review
    must mint Question/AIAnswer/UserComment artifacts and return their IDs."""
    from mathai.math_qa.artifacts import (
        MATH_QA_ARTIFACTS,
        GeneratedAnswerArtifact,
        MathQuestionArtifact,
        UserCommentArtifact,
    )
    from mathai.math_qa.models import (
        GeneratedAnswer,
        MathQuestion,
        UserComment,
    )
    from mathai.math_qa.state import MathQAState
    from mathai.math_qa.execution import build_math_qa_execution

    repo = LocalArtifactRepository(LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts"))
    artifact_store = ArtifactService(repo, registry=MATH_QA_ARTIFACTS)

    class _Workspace:
        def __init__(self, store): self.artifact_store = store

    job_def = build_math_qa_execution(_Workspace(artifact_store))

    from mathai.math_qa.artifacts import LatexAnswerArtifact
    from mathai.math_qa.models import LatexAnswer

    state = MathQAState(
        question=MathQuestion(question_text="2+2", topic="arithmetic"),
        ai_response=GeneratedAnswer(answer_text="4"),
        latex_answer=LatexAnswer(latex_source="\\(2+2=4\\)", validation_attempts=1),
    )
    # Review fires after the LaTeX render now (gate moved in math_qa_policy).
    state.set_review("GenerateLatexStep", UserComment(comment_text="ok", rating=5))

    new_ids = job_def.persistence.on_complete("job-1", state)
    assert len(new_ids) == 4

    artifacts = artifact_store.get_many(new_ids)
    types = {type(a) for a in artifacts}
    assert types == {
        MathQuestionArtifact,
        GeneratedAnswerArtifact,
        LatexAnswerArtifact,
        UserCommentArtifact,
    }

    # Idempotency: with state.artifact_refs populated, a second call mints zero.
    state.artifact_refs = list(new_ids)
    again = job_def.persistence.on_complete("job-1", state)
    assert again == []


def test_math_qa_fetch_result_hydrates_typed_result(tmp_path: Path):
    """fetch_result reads artifact_refs from the checkpoint and rebuilds the
    typed `MathQAResult`."""
    from mathai.math_qa.artifacts import (
        MATH_QA_ARTIFACTS,
        GeneratedAnswerArtifact,
        MathQuestionArtifact,
        UserCommentArtifact,
    )
    from mathai.math_qa.control import build_math_qa_control

    repo = LocalArtifactRepository(LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts"))
    artifact_store = ArtifactService(repo, registry=MATH_QA_ARTIFACTS)

    class _Workspace:
        def __init__(self, store): self.artifact_store = store

    job_def = build_math_qa_control(_Workspace(artifact_store))

    q = MathQuestionArtifact(question_text="2+2", topic="arithmetic")
    a = GeneratedAnswerArtifact(answer_text="4", confidence=0.9)
    r = UserCommentArtifact(comment_text="great", rating=5)
    for art in (q, a, r):
        artifact_store.put(art)

    # Build a record whose result_payload carries the three artifact_refs.
    from unittest.mock import MagicMock
    record = MagicMock()
    record.state.resume_token = None
    record.state.result_payload = {
        "artifact_refs": [str(q.artifact_id), str(a.artifact_id), str(r.artifact_id)],
    }

    result = job_def.fetch_result(record)
    assert result.question is not None and result.question.question_text == "2+2"
    assert result.ai_response is not None and result.ai_response.answer_text == "4"
    assert result.review is not None and result.review.comment_text == "great"
    assert set(result.artifact_refs) == {q.artifact_id, a.artifact_id, r.artifact_id}
