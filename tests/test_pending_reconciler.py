"""Tests for the Celery durability net (issue #67).

`COMPUTE=poll` makes the repo the queue — a PENDING row is rediscovered by the
next `claim_next_pending`, so a lost worker self-heals. `COMPUTE=celery` gives
that up: `enqueue()` pushes to Redis once and nothing re-drives a job whose
push was lost. Two primitives on `GraphJobExecutor` restore the safety net:

- `reconcile_pending_jobs(enqueue, min_age_s)` re-`enqueue`s jobs stuck PENDING
  past a grace window (lost push at submit, redis restart, or a job #62's lease
  reaper just released RUNNING→PENDING).
- `claim_job_for_run(job_id)` is the PENDING-gated claim the celery task uses,
  so a re-enqueue that races a live delivery no-ops on the second.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from ai_platform.jobs.graph_execution import GraphJobExecutor
from ai_platform.utilities.time import utc_now
from ai_platform.workspace.storage.structured.job_repository import (
    JobStatus,
    LocalJobRepository,
)
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig


def _executor(tmp_path: Path) -> GraphJobExecutor:
    repo = LocalJobRepository(LocalRepositoryConfig(root_dir=str(tmp_path), prefix="jobs"))
    return GraphJobExecutor(repo)


def _submit(ex: GraphJobExecutor, job_type: str = "math_qa"):
    return ex.submit_graph_job(
        job_type=job_type, graph_ref="g", initial_state={}, deps_payload={},
    )


def _age_pending(ex: GraphJobExecutor, rec, *, age_s: float):
    """Backdate a PENDING job's `updated_at` so it looks stuck for `age_s`."""
    fresh = ex.repo.get(rec.spec.job_id)
    fresh.state.updated_at = utc_now() - timedelta(seconds=age_s)
    ex.repo.put(fresh)
    return fresh


class _Sink:
    """Collects job_ids handed to `enqueue` — stands in for `run_job.delay`."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, job_id: str) -> None:
        self.calls.append(job_id)


# ---------------------------------------------------------------------------
# claim_job_for_run — the idempotency guard
# ---------------------------------------------------------------------------

def test_claim_for_run_claims_a_pending_job(tmp_path: Path):
    ex = _executor(tmp_path)
    rec = _submit(ex)

    claimed = ex.claim_job_for_run(rec.spec.job_id, worker_id="celery-1")

    assert claimed is not None
    assert claimed.state.status == JobStatus.RUNNING
    assert claimed.state.claimed_by == "celery-1"
    assert claimed.state.attempt == 1
    # Persisted, not just returned in-memory.
    assert ex.repo.get(rec.spec.job_id).state.status == JobStatus.RUNNING


def test_claim_for_run_noops_a_duplicate_delivery(tmp_path: Path):
    """Second delivery of the same job_id (a reconciler re-enqueue racing the
    original message) must not run the job twice."""
    ex = _executor(tmp_path)
    rec = _submit(ex)

    first = ex.claim_job_for_run(rec.spec.job_id, worker_id="celery-1")
    second = ex.claim_job_for_run(rec.spec.job_id, worker_id="celery-2")

    assert first is not None
    assert second is None
    after = ex.repo.get(rec.spec.job_id).state
    # The duplicate left the first claim intact — no extra attempt burned.
    assert after.claimed_by == "celery-1"
    assert after.attempt == 1


def test_claim_for_run_noops_a_terminal_job(tmp_path: Path):
    ex = _executor(tmp_path)
    rec = _submit(ex)
    done = ex.repo.get(rec.spec.job_id)
    done.mark_succeeded(result={})
    ex.repo.put(done)

    assert ex.claim_job_for_run(rec.spec.job_id) is None
    assert ex.repo.get(rec.spec.job_id).state.status == JobStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# reconcile_pending_jobs
# ---------------------------------------------------------------------------

def test_stuck_pending_is_re_enqueued(tmp_path: Path):
    ex = _executor(tmp_path)
    rec = _submit(ex)
    _age_pending(ex, rec, age_s=300)
    sink = _Sink()

    assert ex.reconcile_pending_jobs(sink, min_age_s=120) == 1
    assert sink.calls == [str(rec.spec.job_id)]
    # Reconcile only re-drives; it does not itself change the row's status.
    assert ex.repo.get(rec.spec.job_id).state.status == JobStatus.PENDING


def test_fresh_pending_is_not_re_enqueued(tmp_path: Path):
    """A just-submitted job whose original push may still be in flight must be
    left alone — the grace window prevents re-driving a healthy job."""
    ex = _executor(tmp_path)
    _submit(ex)  # updated_at ~= now, inside the grace window
    sink = _Sink()

    assert ex.reconcile_pending_jobs(sink, min_age_s=120) == 0
    assert sink.calls == []


def test_only_pending_jobs_are_reconciled(tmp_path: Path):
    """An in-flight (RUNNING) or finished job is never re-enqueued, however
    old — that is the 'don't double-run an in-flight job' guarantee."""
    ex = _executor(tmp_path)
    running = _submit(ex)
    r = ex.repo.get(running.spec.job_id)
    r.mark_running(worker_id="w")
    r.state.updated_at = utc_now() - timedelta(seconds=9999)
    ex.repo.put(r)

    succeeded = _submit(ex)
    s = ex.repo.get(succeeded.spec.job_id)
    s.mark_succeeded(result={})
    s.state.updated_at = utc_now() - timedelta(seconds=9999)
    ex.repo.put(s)

    sink = _Sink()
    assert ex.reconcile_pending_jobs(sink, min_age_s=1) == 0
    assert sink.calls == []


def test_reconcile_respects_job_types_scope(tmp_path: Path):
    """A deployment only re-drives the job types it can actually run; other
    runtimes' jobs are left for the pool that serves them."""
    ex = _executor(tmp_path)
    mine = _submit(ex, job_type="math_qa")
    theirs = _submit(ex, job_type="math_conversation")
    _age_pending(ex, mine, age_s=300)
    _age_pending(ex, theirs, age_s=300)
    sink = _Sink()

    n = ex.reconcile_pending_jobs(sink, min_age_s=120, job_types=["math_qa"])
    assert n == 1
    assert sink.calls == [str(mine.spec.job_id)]


def test_reconcile_swallows_enqueue_failure(tmp_path: Path):
    """A re-enqueue that fails (broker still down) must not abort the sweep:
    other jobs are still attempted and the failed one retries next pass."""
    ex = _executor(tmp_path)
    bad = _submit(ex)
    good = _submit(ex)
    _age_pending(ex, bad, age_s=300)
    _age_pending(ex, good, age_s=300)

    seen: list[str] = []

    def flaky(job_id: str) -> None:
        seen.append(job_id)
        if job_id == str(bad.spec.job_id):
            raise RuntimeError("broker down")

    # Both are attempted; only the successful enqueue is counted.
    assert ex.reconcile_pending_jobs(flaky, min_age_s=120) == 1
    assert set(seen) == {str(bad.spec.job_id), str(good.spec.job_id)}
    # The failed one is still PENDING for the next pass.
    assert ex.repo.get(bad.spec.job_id).state.status == JobStatus.PENDING


# ---------------------------------------------------------------------------
# Acceptance scenarios
# ---------------------------------------------------------------------------

def test_lost_enqueue_is_reconciled_and_runs(tmp_path: Path):
    """Acceptance: a job whose submit-time push was lost (stays PENDING) is
    re-enqueued by the sweep and then claimed/run by a worker."""
    ex = _executor(tmp_path)
    rec = _submit(ex)            # push lost — never delivered
    _age_pending(ex, rec, age_s=300)
    sink = _Sink()

    assert ex.reconcile_pending_jobs(sink, min_age_s=120) == 1

    # The re-delivered job is claimable and runs (mirrors `run_job`).
    delivered_id = sink.calls[0]
    claimed = ex.claim_job_for_run(delivered_id, worker_id="celery-1")
    assert claimed is not None and claimed.state.status == JobStatus.RUNNING


def test_reaper_reclaim_is_re_enqueued_under_celery(tmp_path: Path):
    """Acceptance + #62 coordination: a job the lease reaper releases
    RUNNING→PENDING has nothing to re-deliver it under celery — the reconciler
    re-enqueues it so it completes (under poll the next claim would; celery
    needs the sweep)."""
    ex = _executor(tmp_path)
    rec = _submit(ex)
    rec.mark_running(worker_id="w-dead")
    rec.state.heartbeat_at = utc_now() - timedelta(seconds=600)
    ex.repo.put(rec)

    # #62's reaper releases the orphaned RUNNING job back to PENDING…
    assert ex.reclaim_expired_leases(lease_ttl_s=300) == 1
    assert ex.repo.get(rec.spec.job_id).state.status == JobStatus.PENDING

    # …but the reaper just bumped updated_at, so it's inside the grace window
    # this tick (not re-driven yet)…
    sink = _Sink()
    assert ex.reconcile_pending_jobs(sink, min_age_s=120) == 0

    # …and once it ages past the window, the sweep re-enqueues it.
    _age_pending(ex, rec, age_s=300)
    assert ex.reconcile_pending_jobs(sink, min_age_s=120) == 1
    assert sink.calls == [str(rec.spec.job_id)]


def test_reconcile_then_double_delivery_runs_once(tmp_path: Path):
    """End-to-end idempotency: the sweep re-enqueues a stuck job; the first
    delivery claims it; a second (duplicate) delivery is dropped."""
    ex = _executor(tmp_path)
    rec = _submit(ex)
    _age_pending(ex, rec, age_s=300)
    sink = _Sink()

    # Two sweeps before any worker picks it up → two deliveries of the same id.
    ex.reconcile_pending_jobs(sink, min_age_s=120)
    ex.reconcile_pending_jobs(sink, min_age_s=120)
    assert len(sink.calls) == 2 and len(set(sink.calls)) == 1

    job_id = sink.calls[0]
    first = ex.claim_job_for_run(job_id, worker_id="celery-1")
    second = ex.claim_job_for_run(job_id, worker_id="celery-2")
    assert first is not None and second is None
    assert ex.repo.get(rec.spec.job_id).state.attempt == 1
