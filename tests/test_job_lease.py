"""Tests for the job-lease reaper (issue #62).

A worker that dies mid-job (crash / OOM / SIGKILL, or wedged-then-restarted)
leaves its `JobRecord` stuck in RUNNING with nothing to advance or fail it.
`GraphJobExecutor.reclaim_expired_leases` reclaims such orphans: a live worker
refreshes `heartbeat_at` at each graph step, so a row whose heartbeat has aged
past the lease TTL is presumed abandoned and released back to PENDING for
re-claim (or FAILED once the retry budget is exhausted).
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from ai_platform.compute.poll import PollingComputeBackend
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


def _running(ex: GraphJobExecutor, *, heartbeat_age_s: float, worker_id="w-dead"):
    """Submit a job, mark it RUNNING, and backdate its heartbeat."""
    rec = _submit(ex)
    rec.mark_running(worker_id=worker_id)
    rec.state.heartbeat_at = utc_now() - timedelta(seconds=heartbeat_age_s)
    ex.repo.put(rec)
    return rec


# ---------------------------------------------------------------------------
# reclaim_expired_leases
# ---------------------------------------------------------------------------

def test_fresh_lease_is_not_reclaimed(tmp_path: Path):
    ex = _executor(tmp_path)
    rec = _running(ex, heartbeat_age_s=10)

    assert ex.reclaim_expired_leases(lease_ttl_s=300) == 0
    assert ex.repo.get(rec.spec.job_id).state.status == JobStatus.RUNNING


def test_expired_lease_released_to_pending(tmp_path: Path):
    ex = _executor(tmp_path)
    rec = _running(ex, heartbeat_age_s=600)

    assert ex.reclaim_expired_leases(lease_ttl_s=300) == 1
    reclaimed = ex.repo.get(rec.spec.job_id).state
    assert reclaimed.status == JobStatus.PENDING
    # Cleared so the next claim starts clean…
    assert reclaimed.claimed_by is None
    assert reclaimed.heartbeat_at is None
    # …but the attempt count is preserved so the retry budget still applies.
    assert reclaimed.attempt == 1


def test_reclaimed_job_is_claimable_again(tmp_path: Path):
    ex = _executor(tmp_path)
    rec = _running(ex, heartbeat_age_s=600)

    ex.reclaim_expired_leases(lease_ttl_s=300)
    claimed = ex.claim_next_pending(job_type="math_qa", worker_id="w-fresh")

    assert claimed is not None and claimed.spec.job_id == rec.spec.job_id
    assert claimed.state.status == JobStatus.RUNNING
    assert claimed.state.claimed_by == "w-fresh"
    # First claim → attempt 1, reclaim preserves it, second claim → attempt 2.
    assert claimed.state.attempt == 2


def test_expired_lease_with_attempts_exhausted_fails(tmp_path: Path):
    ex = _executor(tmp_path)
    rec = _submit(ex)
    # Drive attempts up to the spec ceiling (default max_attempts=3).
    rec.mark_running(worker_id="w-dead")
    rec.state.attempt = rec.spec.max_attempts
    rec.state.heartbeat_at = utc_now() - timedelta(seconds=600)
    ex.repo.put(rec)

    assert ex.reclaim_expired_leases(lease_ttl_s=300) == 1
    after = ex.repo.get(rec.spec.job_id).state
    assert after.status == JobStatus.FAILED
    assert after.error_retryable is False
    assert "Lease expired" in (after.error_message or "")


def test_only_running_jobs_are_reclaimed(tmp_path: Path):
    ex = _executor(tmp_path)
    # A stale-but-terminal/waiting/pending job must never be touched: only
    # RUNNING rows can be orphaned by a dead worker.
    pending = _submit(ex)
    succeeded = _submit(ex)
    s = ex.repo.get(succeeded.spec.job_id)
    s.mark_succeeded(result={})
    s.state.heartbeat_at = utc_now() - timedelta(seconds=9999)
    ex.repo.put(s)

    assert ex.reclaim_expired_leases(lease_ttl_s=1) == 0
    assert ex.repo.get(pending.spec.job_id).state.status == JobStatus.PENDING
    assert ex.repo.get(succeeded.spec.job_id).state.status == JobStatus.SUCCEEDED


def test_reclaim_counts_only_expired(tmp_path: Path):
    ex = _executor(tmp_path)
    _running(ex, heartbeat_age_s=10)    # fresh
    _running(ex, heartbeat_age_s=600)   # expired
    _running(ex, heartbeat_age_s=900)   # expired

    assert ex.reclaim_expired_leases(lease_ttl_s=300) == 2


# ---------------------------------------------------------------------------
# heartbeat refresh keeps a progressing job alive
# ---------------------------------------------------------------------------

def test_update_progress_refreshes_lease(tmp_path: Path):
    ex = _executor(tmp_path)
    rec = _running(ex, heartbeat_age_s=600)

    # A live worker advancing the graph would call this between nodes; it must
    # refresh the lease so the very next reaper pass leaves the job alone.
    ex.update_progress(rec.spec.job_id, stage="Step2", message="working")

    assert ex.reclaim_expired_leases(lease_ttl_s=300) == 0
    assert ex.repo.get(rec.spec.job_id).state.status == JobStatus.RUNNING


# ---------------------------------------------------------------------------
# poll loop wiring
# ---------------------------------------------------------------------------

def test_poll_worker_reaps_on_boot(tmp_path: Path):
    ex = _executor(tmp_path)
    rec = _running(ex, heartbeat_age_s=600)

    # job_definitions={} → the worker serves nothing, so the loop won't *run*
    # the reclaimed job; we only assert the boot reap released it to PENDING.
    backend = PollingComputeBackend(ex, job_definitions={})
    backend.start_worker(worker_id="w", once=True, job_lease_ttl_s=300)

    assert ex.repo.get(rec.spec.job_id).state.status == JobStatus.PENDING


def test_poll_worker_lease_off_by_default(tmp_path: Path):
    ex = _executor(tmp_path)
    rec = _running(ex, heartbeat_age_s=99999)

    # No TTL configured → reaper disabled, even a very stale RUNNING job stays.
    backend = PollingComputeBackend(ex, job_definitions={})
    backend.start_worker(worker_id="w", once=True, job_lease_ttl_s=None)

    assert ex.repo.get(rec.spec.job_id).state.status == JobStatus.RUNNING
