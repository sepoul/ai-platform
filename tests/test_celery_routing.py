"""Per-runtime Celery routing (issue #66, epic #64).

Option A: route `run_job` to a queue per runtime so the `default`
(pydantic_ai: math_qa/math_notes) and `crewai` (math_conversation)
consumers each receive only the jobs they can import — mirroring the
two-poll-worker topology.

These pin the producer side: `CeleryComputeBackend.enqueue` picks the
queue from the job's runtime. No live broker / no celery worker is
needed — the producer's `send_task` is stubbed so enqueue records the
queue it would publish to. The producer enqueues by task NAME and never
imports the worker's task module (issue #72); the fixture poisons that
module to prove it.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from ai_platform.compute.base import EnqueueUnavailable
from ai_platform.compute.celery import (
    CeleryComputeBackend,
    RUN_JOB_TASK_NAME,
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
    """Capture the queue each enqueue would publish to, without a live broker.

    The producer publishes by task NAME through a Celery app it builds itself
    (`send_task`) and must NEVER import the worker's task module
    (`ai_platform.entrypoints.celery_app`), which is absent from the api image
    (issue #72). We (a) poison that module in `sys.modules` so any import of it
    raises `ImportError` — a regression trip-wire if `enqueue` ever reaches for
    it again — and (b) stub the producer app's `send_task` to record the queue
    instead of hitting Redis. Returns the list of queues.
    """
    monkeypatch.setitem(sys.modules, "ai_platform.entrypoints.celery_app", None)

    queues: list[str] = []
    fake_app = MagicMock()
    fake_app.send_task.side_effect = lambda *a, **k: queues.append(k.get("queue"))
    monkeypatch.setattr(
        CeleryComputeBackend, "_producer_app", lambda self: fake_app
    )
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


# ---------------------------------------------------------------------------
# Acceptance (issue #72): enqueue by NAME, with the worker package absent
# ---------------------------------------------------------------------------

def test_enqueue_publishes_run_job_by_name_not_an_imported_task(monkeypatch):
    """The producer must publish with `send_task("run_job", …)` — by NAME — so
    it works in the split api image where the worker's task module is absent.
    `routed_queues` already poisons `…celery_app`; here we assert the full
    call shape (name + args + queue), not just the queue."""
    monkeypatch.setitem(sys.modules, "ai_platform.entrypoints.celery_app", None)

    calls: list[tuple] = []
    fake_app = MagicMock()
    fake_app.send_task.side_effect = lambda *a, **k: calls.append((a, k))
    monkeypatch.setattr(
        CeleryComputeBackend, "_producer_app", lambda self: fake_app
    )

    # No import of the worker task module may happen — if `enqueue` reached for
    # it the poisoned entry above would raise ImportError here.
    CeleryComputeBackend(MagicMock(), {}).enqueue("job-1")

    (args, kwargs) = calls[0]
    assert args[0] == RUN_JOB_TASK_NAME == "run_job"
    assert kwargs["args"] == ["job-1"]
    assert kwargs["queue"] == "runtime.default"


def test_producer_app_builds_real_celery_app_and_send_task_is_used(monkeypatch):
    """Exercise the REAL `_producer_app` (not the fixture's stub): it builds a
    Celery app from `CELERY_BROKER_URL` with no worker import, and `enqueue`
    routes through that app's `send_task`. Uses the in-memory broker so no
    Redis is required and only `send_task` is stubbed."""
    monkeypatch.setenv("CELERY_BROKER_URL", "memory://")
    monkeypatch.setitem(sys.modules, "ai_platform.entrypoints.celery_app", None)

    backend = CeleryComputeBackend(MagicMock(), {})
    app = backend._producer_app()  # real Celery app, built from the broker URL
    assert app.conf.broker_url == "memory://"

    sent: dict = {}
    monkeypatch.setattr(app, "send_task", lambda name, **k: sent.update(name=name, **k))
    backend.enqueue("job-9")

    assert sent["name"] == "run_job"
    assert sent["args"] == ["job-9"]
    assert sent["queue"] == "runtime.default"
    # Cached: a second enqueue reuses the same app (one connection pool).
    assert backend._producer_app() is app


def test_broker_unavailable_is_reported_as_enqueue_unavailable(monkeypatch):
    """A broker-down publish (kombu `OperationalError`) is translated to the
    platform's `EnqueueUnavailable` so the API's best-effort enqueue leaves the
    job PENDING for the reconciler instead of 500-ing the submit (issues
    #72/#67)."""
    from kombu.exceptions import OperationalError

    fake_app = MagicMock()
    fake_app.send_task.side_effect = OperationalError("redis down")
    monkeypatch.setattr(
        CeleryComputeBackend, "_producer_app", lambda self: fake_app
    )

    with pytest.raises(EnqueueUnavailable):
        CeleryComputeBackend(MagicMock(), {}).enqueue("j")


def test_producer_misconfig_propagates_and_is_not_swallowed(monkeypatch):
    """A producer misconfiguration (here an import/routing-style error) is NOT
    a transient broker outage — it must propagate raw, never be repackaged as
    `EnqueueUnavailable` (which the API swallows). This is the bug #72 fixes:
    such an error used to hide as a permanent silent PENDING."""
    fake_app = MagicMock()
    fake_app.send_task.side_effect = ModuleNotFoundError("no worker task module")
    monkeypatch.setattr(
        CeleryComputeBackend, "_producer_app", lambda self: fake_app
    )

    with pytest.raises(ModuleNotFoundError):
        CeleryComputeBackend(MagicMock(), {}).enqueue("j")


# ---------------------------------------------------------------------------
# Composition with the #67 durability net: the reconciler must re-push through
# the SAME per-runtime routing as submit, scoped to this pool's own runtime.
# ---------------------------------------------------------------------------

def test_reconciler_reenqueues_through_per_runtime_queue(monkeypatch):
    """`reconcile_jobs` (issue #67) re-drives stuck-PENDING jobs. It must route
    each re-push through THIS pool's per-runtime queue — explicit
    `apply_async(queue=...)`, mirroring the producer — not a bare `delay` onto a
    shared/default queue. So a re-driven crewai job returns to the crewai
    consumer, never the default one."""
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    import importlib

    celery_app = importlib.import_module("ai_platform.entrypoints.celery_app")

    captured: dict = {}
    monkeypatch.setattr(
        celery_app.run_job,
        "apply_async",
        lambda *a, **k: captured.update(args=k.get("args"), queue=k.get("queue")),
    )

    celery_app._reenqueue_for_runtime("job-123")

    # Routes via apply_async to an explicit per-runtime queue matching this
    # pool's runtime — not a None/default queue and not a bare delay.
    assert captured["args"] == ["job-123"]
    assert captured["queue"] == celery_app.celery_queue_for_runtime(celery_app.RUNTIME)
    assert captured["queue"].startswith("runtime.")


def test_reconciler_is_scoped_to_this_pools_runtime_job_types(tmp_path, monkeypatch):
    """The sweep re-enqueues only THIS pool's runtime job_types (runtime-scoped
    `_domains`), leaving other runtimes' PENDING jobs for their own pool — so
    the default pool never re-pushes a crewai job and vice versa."""
    from datetime import timedelta

    from ai_platform.jobs.graph_execution import GraphJobExecutor
    from ai_platform.utilities.time import utc_now
    from ai_platform.workspace.storage.structured.job_repository import (
        LocalJobRepository,
    )
    from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig

    repo = LocalJobRepository(
        LocalRepositoryConfig(root_dir=str(tmp_path), prefix="jobs")
    )
    ex = GraphJobExecutor(repo)
    # Two stuck-PENDING jobs, one per runtime; age them past any grace window.
    for jt in ("math_qa", "math_conversation"):
        rec = ex.submit_graph_job(
            job_type=jt, graph_ref="g", initial_state={}, deps_payload={}
        )
        rec.state.updated_at = utc_now() - timedelta(seconds=10_000)
        repo.put(rec)

    pushed: list[str] = []
    # A default-runtime pool only serves (and so only reconciles) math_qa.
    ex.reconcile_pending_jobs(
        lambda jid: pushed.append(ex.repo.get(jid).spec.job_type),
        min_age_s=1.0,
        job_types=["math_qa"],
    )
    assert pushed == ["math_qa"]  # the crewai job is left for the crewai pool
