"""Tests for `result_fetcher` — ref extraction across the checkpoint /
result_payload sources, and the ungated-job fall-through.

The load-bearing case: an ungated single-node job saves its resume-token
checkpoint *before* `End → _run_persist` appends the minted artifact id to
`state.artifact_refs`, so the checkpoint's refs are empty. `_extract_refs` must
fall through to `result_payload` (which the job's `extract_result` populates)
instead of early-returning the empty checkpoint list — otherwise
`GET /jobs/{id}/result` can't hydrate the artifact even though it exists.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from ai_platform.jobs.checkpoint import GraphCheckpoint
from ai_platform.jobs.result_fetcher import _extract_refs, hydrate_artifact_refs


def _record(*, resume_token=None, result_payload=None):
    return SimpleNamespace(
        state=SimpleNamespace(resume_token=resume_token, result_payload=result_payload)
    )


def _checkpoint_token(artifact_refs: list[str]) -> str:
    return GraphCheckpoint(
        state_data={"artifact_refs": artifact_refs},
        next_node_key="__done__",
    ).model_dump_json()


def test_ungated_job_falls_through_empty_checkpoint_to_result_payload():
    aid = str(uuid4())
    rec = _record(
        resume_token=_checkpoint_token([]),  # saved pre-persist → empty
        result_payload={"artifact_refs": [aid]},  # extract_result stamped it
    )
    assert _extract_refs(rec) == [UUID(aid)]


def test_checkpoint_with_refs_wins_over_result_payload():
    a, b = str(uuid4()), str(uuid4())
    rec = _record(
        resume_token=_checkpoint_token([a]),
        result_payload={"artifact_refs": [b]},  # ignored — checkpoint has refs
    )
    assert _extract_refs(rec) == [UUID(a)]


def test_no_token_uses_result_payload():
    aid = str(uuid4())
    rec = _record(resume_token=None, result_payload={"artifact_refs": [aid]})
    assert _extract_refs(rec) == [UUID(aid)]


def test_empty_everywhere_returns_empty():
    assert _extract_refs(_record()) == []
    assert (
        _extract_refs(_record(resume_token=_checkpoint_token([]), result_payload={}))
        == []
    )


def test_malformed_token_falls_through_to_result_payload():
    aid = str(uuid4())
    rec = _record(resume_token="not-json", result_payload={"artifact_refs": [aid]})
    assert _extract_refs(rec) == [UUID(aid)]


def test_hydrate_calls_get_many_with_extracted_ids():
    aid = uuid4()
    captured: dict = {}

    class _Api:
        def get_many(self, ids):
            captured["ids"] = ids
            return ["ARTIFACT"]

    out = hydrate_artifact_refs(_record(result_payload={"artifact_refs": [str(aid)]}), _Api())
    assert out == ["ARTIFACT"]
    assert captured["ids"] == [aid]


def test_hydrate_empty_skips_get_many():
    class _Api:
        def get_many(self, ids):
            raise AssertionError("get_many must not be called for empty refs")

    assert hydrate_artifact_refs(_record(), _Api()) == []
