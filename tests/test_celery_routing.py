"""Per-runtime Celery routing (issue #66, epic #64).

Option A: route `run_job` to a queue per runtime so the `default`
(pydantic_ai: math_qa/math_notes) and `crewai` (math_conversation)
consumers each receive only the jobs they can import — mirroring the
two-poll-worker topology.

These pin the producer side: `CeleryComputeBackend.enqueue` picks the
queue from the job's runtime. No live broker / no celery worker is
needed — the lazily-imported `run_job` task is stubbed so enqueue
records the queue it would publish to.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from ai_platform.compute.celery import (
    CeleryComputeBackend,
    celery_queue_for_runtime,
)


# ---------------------------------------------------------------------------
# Queue naming — the single source of truth shared by producer + consumer
# ---------------------------------------------------------------------------

def test_queue_name_is_one_per_runtime():
    assert celery_queue_for_runtime("default") == "runtime.default"
    assert celery_queue_for_runtime("crewai") == "runtime.crewai"
    # Distinct runtimes never collide on a queue.
    assert celery_queue_for_runtime("default") != celery_queue_for_runtime("crewai")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _fake_record(job_type: str):
    return types.SimpleNamespace(spec=types.SimpleNamespace(job_type=job_type))


def _backend(jobs: dict[str, str], runtimes: dict[str, str]) -> CeleryComputeBackend:
    """A backend wired to a fake repo (`jobs`: job_id -> job_type) and a
    runtime resolver (`runtimes`: job_type -> runtime)."""
    repo = MagicMock()
    repo.get.side_effect = lambda jid: _fake_record(jobs[jid])
    executor = MagicMock()
    executor.repo = repo
    return CeleryComputeBackend(
        executor, {}, runtime_for_job_type=lambda jt: runtimes[jt]
    )


@pytest.fixture
def routed_queues(monkeypatch):
    """Stub the lazily-imported `run_job` so enqueue records the target queue
    instead of publishing to a real broker. Returns the list of queues."""
    queues: list[str] = []
    task = MagicMock()
    task.apply_async.side_effect = lambda *a, **k: queues.append(k.get("queue"))
    module = types.ModuleType("ai_platform.entrypoints.celery_app")
    module.run_job = task
    monkeypatch.setitem(sys.modules, "ai_platform.entrypoints.celery_app", module)
    return queues


# ---------------------------------------------------------------------------
# Acceptance: one job per runtime → handled by the correct consumer
# ---------------------------------------------------------------------------

def test_each_runtime_routes_to_its_own_consumer(routed_queues):
    backend = _backend(
        jobs={"j-default": "math_qa", "j-crewai": "math_conversation"},
        runtimes={"math_qa": "default", "math_conversation": "crewai"},
    )

    backend.enqueue("j-default")
    backend.enqueue("j-crewai")

    # The default job lands on the queue the default consumer consumes; the
    # crewai job on the crewai consumer's queue. The consumer's queue is
    # derived from the same helper off its WORKER_RUNTIME (see celery_app).
    assert routed_queues == [
        celery_queue_for_runtime("default"),
        celery_queue_for_runtime("crewai"),
    ]


def test_crewai_job_never_lands_on_the_default_queue(routed_queues):
    backend = _backend(
        jobs={"j": "math_conversation"},
        runtimes={"math_conversation": "crewai"},
    )

    backend.enqueue("j")

    # The whole point of routing: a crewai job must not reach the default
    # pool (which lacks the CrewAI stack and couldn't import the domain).
    assert routed_queues == ["runtime.crewai"]
    assert celery_queue_for_runtime("default") not in routed_queues


def test_unresolved_runtime_falls_back_to_default_queue(routed_queues):
    # No resolver wired (single-pool / cold-boot fallback) → default queue.
    backend = CeleryComputeBackend(MagicMock(), {})
    backend.enqueue("whatever")
    assert routed_queues == ["runtime.default"]


def test_resolver_failure_falls_back_to_default_queue(routed_queues):
    # A repo/catalog hiccup must not wedge submit — degrade to default queue.
    executor = MagicMock()
    executor.repo.get.side_effect = RuntimeError("catalog down")
    backend = CeleryComputeBackend(
        executor, {}, runtime_for_job_type=lambda jt: "crewai"
    )
    backend.enqueue("j")
    assert routed_queues == ["runtime.default"]
