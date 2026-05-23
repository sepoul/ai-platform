"""Tests for per-runtime worker isolation.

A worker serves one runtime (WORKER_RUNTIME) and only claims jobs whose
JobDefinition.runtime matches; jobs for other runtimes stay PENDING for
the pool that can run them. This is what lets CrewAI (otel-sdk <1.35) and
Logfire (otel-sdk >=1.39) live in separate worker environments.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_platform.jobs.graph_execution import GraphJobExecutor
from ai_platform.jobs.runtimes import (
    DEFAULT_RUNTIME,
    current_worker_runtime,
    select_for_runtime,
)
from ai_platform.workspace.storage.structured.job_repository import (
    JobStatus,
    LocalJobRepository,
)
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig


def _executor(tmp_path: Path) -> GraphJobExecutor:
    repo = LocalJobRepository(LocalRepositoryConfig(root_dir=str(tmp_path), prefix="jobs"))
    return GraphJobExecutor(repo)


def _submit(ex: GraphJobExecutor, job_type: str):
    return ex.submit_graph_job(
        job_type=job_type, graph_ref="g", initial_state={}, deps_payload={},
    )


# ---------------------------------------------------------------------------
# claim_next_pending allowlist
# ---------------------------------------------------------------------------

def test_claim_allowlist_claims_only_served_type(tmp_path: Path):
    ex = _executor(tmp_path)
    _submit(ex, "math_qa")
    convo = _submit(ex, "math_conversation")

    # A default worker (serves math_qa) claims the math_qa job…
    claimed = ex.claim_next_pending(job_types=["math_qa"], worker_id="w-default")
    assert claimed is not None and claimed.spec.job_type == "math_qa"

    # …and leaves the math_conversation job PENDING for the crewai pool.
    still = ex.repo.get(convo.spec.job_id)
    assert still.state.status == JobStatus.PENDING

    # The crewai worker then claims it.
    claimed2 = ex.claim_next_pending(job_types=["math_conversation"], worker_id="w-crewai")
    assert claimed2 is not None and claimed2.spec.job_type == "math_conversation"


def test_claim_allowlist_none_when_only_other_runtime_pending(tmp_path: Path):
    ex = _executor(tmp_path)
    _submit(ex, "math_conversation")
    # Default worker finds nothing it serves; the crewai job is untouched.
    assert ex.claim_next_pending(job_types=["math_qa"], worker_id="w") is None
    assert ex.repo.list(status=JobStatus.PENDING)[0].spec.job_type == "math_conversation"


def test_claim_allowlist_empty_serves_nothing(tmp_path: Path):
    ex = _executor(tmp_path)
    _submit(ex, "math_qa")
    assert ex.claim_next_pending(job_types=[], worker_id="w") is None


def test_single_type_claim_still_works(tmp_path: Path):
    """Back-compat: the original job_type / None paths are unchanged."""
    ex = _executor(tmp_path)
    _submit(ex, "math_qa")
    claimed = ex.claim_next_pending(job_type="math_qa", worker_id="w")
    assert claimed is not None and claimed.spec.job_type == "math_qa"


# ---------------------------------------------------------------------------
# select_for_runtime + JobDefinition.runtime declarations
# ---------------------------------------------------------------------------

def test_select_for_runtime_partitions_job_defs():
    from dataclasses import dataclass

    @dataclass
    class _JD:
        runtime: str

    defs = {"a": _JD(runtime="default"), "b": _JD(runtime="crewai"), "c": _JD(runtime="default")}
    assert set(select_for_runtime(defs, "default")) == {"a", "c"}
    assert set(select_for_runtime(defs, "crewai")) == {"b"}
    assert select_for_runtime(defs, "nope") == {}


def test_math_conversation_declares_crewai_runtime(tmp_path: Path):
    from ai_platform.jobs.artifact_service import ArtifactService
    from ai_platform.workspace.storage.structured.artifact_repository import LocalArtifactRepository
    from mathai.math_conversation.artifacts import MATH_CONVERSATION_ARTIFACTS
    from mathai.math_conversation.workflow import build_math_conversation_job_definition

    repo = LocalArtifactRepository(LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts"))
    store = ArtifactService(repo, registry=MATH_CONVERSATION_ARTIFACTS)

    class _WS:
        artifact_store = store

    jd = build_math_conversation_job_definition(_WS())
    assert jd.runtime == "crewai"


def test_default_runtime_constant_and_env():
    import os
    assert DEFAULT_RUNTIME == "default"
    assert current_worker_runtime() == "default"
    os.environ["WORKER_RUNTIME"] = "crewai"
    try:
        assert current_worker_runtime() == "crewai"
    finally:
        os.environ.pop("WORKER_RUNTIME")


# ---------------------------------------------------------------------------
# composition root imports only a runtime's domains (import isolation)
# ---------------------------------------------------------------------------

def test_composition_root_partitions_domains_by_runtime():
    from mathapp.composition_root import all_domains, domains_for_runtime
    default_mods = {m.__module__ for m in domains_for_runtime("default")}
    crewai_mods = {m.__module__ for m in domains_for_runtime("crewai")}
    assert default_mods == {"mathai.domain"}
    assert crewai_mods == {"mathai.math_conversation.domain"}
    # The crewai runtime must NOT pull math_qa (which imports logfire).
    assert "mathai.domain" not in crewai_mods
    assert len(all_domains()) == 2
