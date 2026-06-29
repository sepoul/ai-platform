from __future__ import annotations
import logging
from ai_platform.utilities.time import utc_now
from typing import TYPE_CHECKING, Any, Callable, Protocol, TypeVar
from uuid import UUID
from pydantic import BaseModel

from ai_platform.jobs.checkpoint import GraphCheckpoint  # re-exported for callers
from ai_platform.workspace.storage.protocols import JobRepository
from ai_platform.workspace.storage.structured.job_repository import JobRecord, JobStatus

if TYPE_CHECKING:
    # Only used in a Protocol return annotation (stringized by `from __future__
    # import annotations`), so the engine is never imported at runtime — which
    # keeps GraphJobExecutor importable in the engine-free control plane.
    from pydantic_graph import BaseNode, End

logger = logging.getLogger(__name__)

__all__ = ["GraphCheckpoint", "GraphJobExecutor"]


# ---------------------------------------------------------------------------
# Graph runner protocol
# ---------------------------------------------------------------------------

StateT = TypeVar("StateT", bound=BaseModel)
DepsT = TypeVar("DepsT")
OutputT = TypeVar("OutputT")


class GraphRunner(Protocol[StateT, DepsT, OutputT]):
    """
    Protocol for any graph-based runner.
    Expects: start_run, step, resume.
    """

    async def step(
        self, deps: DepsT, state: StateT, **kwargs: Any
    ) -> End[OutputT] | BaseNode[StateT, DepsT]:
        """Run one step of the graph. Return End if done, else next node."""
        ...


# ---------------------------------------------------------------------------
# Job-graph bridge
# ---------------------------------------------------------------------------

class GraphJobExecutor:
    """
    Thin layer to execute pydantic_graph-based jobs stored in a JobRepository.
    """

    def __init__(self, job_repo: JobRepository):
        self.repo = job_repo

    def submit_graph_job(
        self,
        job_type: str,
        graph_ref: str,
        initial_state: dict[str, Any],
        deps_payload: dict[str, Any] | None = None,
        workspace_ref: str | None = None,
        created_by: str | None = None,
    ) -> JobRecord:
        """
        Submit a new job for a graph run.
        initial_state: serialized pydantic state (e.g. MathQAState.model_dump())
        deps_payload: serialized dependencies (e.g. InputsSourcer params)
        """
        record = JobRecord.create(
            job_type=job_type,
            graph_ref=graph_ref,
            input_payload={"state": initial_state, "deps": deps_payload or {}},
            workspace_ref=workspace_ref,
            created_by=created_by,
        )
        self.repo.put(record)
        return record

    def mark_running(self, job_id: str | UUID, worker_id: str | None = None) -> JobRecord:
        """Claim job and mark it running."""
        record = self.repo.get(job_id)
        record.mark_running(worker_id=worker_id)
        self.repo.put(record)
        return record

    def claim_job_for_run(
        self, job_id: str | UUID, worker_id: str | None = None
    ) -> JobRecord | None:
        """Claim a *specific* job a push backend (Celery) delivered, but only
        if it's still PENDING. Returns the now-RUNNING record, or None if the
        job is no longer claimable (already RUNNING/terminal).

        This is the idempotency guard for the durability net (issue #67): the
        PENDING reconciler re-`enqueue`s jobs whose original push was lost, so
        the same `job_id` can be delivered to `run_job` more than once (a
        re-enqueue that races the original message, or a redis redelivery). An
        unconditional `mark_running` would let both deliveries run the job
        twice; gating on PENDING means the second delivery is a clean no-op.

        Unlike `claim_next_pending`, the broker already chose the job, so this
        does not scan for the next pending row — it claims this exact one or
        declines. The single-blob local repo can't make the check-and-set
        atomic (noted on `put`); under the at-least-once celery model this
        still closes all but a sub-millisecond window, and a double-run is
        bounded by `spec.max_attempts` regardless.
        """
        record = self.repo.get(job_id)
        if record.state.status != JobStatus.PENDING:
            return None
        record.mark_running(worker_id=worker_id)
        self.repo.put(record)
        return record

    def save_checkpoint(
        self,
        job_id: str | UUID,
        state: dict[str, Any],
        next_node_key: str,
        reason: str | None = None,
        gated_node: str | None = None,
    ) -> JobRecord:
        """Pause job with checkpoint for resumption (status → WAITING_INPUT)."""
        record = self.repo.get(job_id)
        checkpoint = GraphCheckpoint(
            state_data=state,
            next_node_key=next_node_key,
            gated_node=gated_node,
            attempt=record.state.attempt,
        )
        record.mark_waiting(reason=reason or "checkpoint", resume_token=checkpoint.model_dump_json())
        self.repo.put(record)
        return record

    def load_checkpoint(self, job_id: str | UUID) -> GraphCheckpoint | None:
        """Load checkpoint from job.state.resume_token if present."""
        record = self.repo.get(job_id)
        if not record.state.resume_token:
            return None
        return GraphCheckpoint.model_validate_json(record.state.resume_token)

    def complete_job(
        self,
        job_id: str | UUID,
        result: dict[str, Any] | None = None,
        artifact_refs: list[UUID] | None = None,
    ) -> JobRecord:
        """Mark job as succeeded with final result.

        `artifact_refs` is the execution state's minted refs; persisting
        them here (not re-deriving from the re-read record) is what makes
        `GET /jobs/{id}/result` hydration reliable — see PR-3e.
        """
        record = self.repo.get(job_id)
        record.mark_succeeded(result=result, artifact_refs=artifact_refs)
        record.state.stage = "completed"
        record.state.percent = 100.0
        record.state.message = "Job completed successfully"
        self.repo.put(record)
        return record

    def fail_job(
        self,
        job_id: str | UUID,
        error: str,
        retryable: bool = False,
    ) -> JobRecord:
        """Mark job as failed."""
        record = self.repo.get(job_id)
        record.mark_failed(error=error, retryable=retryable)
        self.repo.put(record)
        return record

    def update_progress(
        self,
        job_id: str | UUID,
        stage: str | None = None,
        percent: float | None = None,
        message: str | None = None,
    ) -> JobRecord:
        """Update job progress metadata."""
        record = self.repo.get(job_id)
        record.update_progress(stage=stage, percent=percent, message=message)
        self.repo.put(record)
        return record

    def claim_next_pending(
        self,
        job_type: str | None = None,
        worker_id: str | None = None,
        max_age_s: float | None = None,
        job_types: list[str] | None = None,
    ) -> JobRecord | None:
        """
        Simple claim: find first PENDING job (optionally filtered by type),
        mark RUNNING and return it.
        Returns None if no jobs available.

        `job_types` is a runtime allowlist: when set, only jobs whose type
        is in it are claimable (each served type is probed newest-first).
        This is how a worker stays scoped to its `WORKER_RUNTIME` — jobs
        for other runtimes are left PENDING for the pool that can run them.
        Mutually exclusive with `job_type`; if both are given, `job_types`
        wins.

        If `max_age_s` is set, jobs whose `created_at` is older than that
        threshold are ignored. The repo list is ordered newest-first, so
        a single sample is sufficient: if the newest pending is stale,
        every other pending is too.
        """
        if job_types is not None:
            # Probe each served type; claim the first that has a pending job.
            for candidate in job_types:
                record = self.claim_next_pending(
                    job_type=candidate, worker_id=worker_id, max_age_s=max_age_s,
                )
                if record is not None:
                    return record
            return None

        jobs = self.repo.list(status=JobStatus.PENDING, job_type=job_type, limit=1)
        if not jobs:
            return None
        record = jobs[0]
        if max_age_s is not None:
            age_s = (utc_now() - record.created_at).total_seconds()
            if age_s > max_age_s:
                logger.info(
                    "Skipping stale pending job %s (age=%.0fs > max=%.0fs)",
                    record.spec.job_id, age_s, max_age_s,
                )
                return None
        record.mark_running(worker_id=worker_id)
        self.repo.put(record)
        return record

    def reclaim_expired_leases(self, lease_ttl_s: float) -> int:
        """Reclaim RUNNING jobs whose lease has expired — a worker that died
        mid-job (crash/OOM/SIGKILL, or wedged-then-restarted) leaves its row
        stuck in RUNNING with nothing to advance or fail it. Returns the
        number of jobs reclaimed.

        A live worker refreshes `heartbeat_at` at each graph step (see
        `update_progress`); a dead one stops, so its lease ages past
        `lease_ttl_s`. Such orphans are released back to PENDING for re-claim,
        or marked FAILED once `spec.max_attempts` is exhausted so a job that
        wedges every worker can't loop forever. This is the defense-in-depth
        half of issue #62 — the DB-socket fail-fast (`make_pool`) stops a
        *live* worker from wedging; this reclaims work a *dead* worker left
        behind.

        Safety: in the single-threaded poll model the loop only runs this
        between jobs (a busy worker isn't polling), so it never reaps the job
        it is itself running. Across workers, `lease_ttl_s` must exceed the
        longest gap between a healthy job's progress updates, or a slow job
        could be reclaimed while still live — keep it comfortably large.
        """
        running = self.repo.list(status=JobStatus.RUNNING)
        now = utc_now()
        reclaimed = 0
        for record in running:
            # `heartbeat_at` is set at claim (`mark_running`) and refreshed on
            # every progress update; fall back to `updated_at` for any legacy
            # row written before heartbeats existed.
            last_seen = record.state.heartbeat_at or record.state.updated_at
            age_s = (now - last_seen).total_seconds()
            if age_s <= lease_ttl_s:
                continue

            job_id = record.spec.job_id
            if record.state.attempt >= record.spec.max_attempts:
                record.mark_failed(
                    error=(
                        f"Lease expired: no heartbeat for {age_s:.0f}s "
                        f"(> {lease_ttl_s:.0f}s) and {record.state.attempt} of "
                        f"{record.spec.max_attempts} attempt(s) used — worker "
                        f"presumed dead, retry budget exhausted."
                    ),
                    retryable=False,
                )
                logger.warning(
                    "Lease expired for job %s (age=%.0fs); max attempts "
                    "exhausted — marking FAILED", job_id, age_s,
                )
            else:
                record.mark_pending_for_reclaim()
                logger.warning(
                    "Lease expired for job %s (age=%.0fs > %.0fs); worker "
                    "presumed dead — releasing to PENDING for re-claim",
                    job_id, age_s, lease_ttl_s,
                )
            self.repo.put(record)
            reclaimed += 1
        return reclaimed

    def reconcile_pending_jobs(
        self,
        enqueue: Callable[[str], None],
        min_age_s: float,
        *,
        job_types: list[str] | None = None,
    ) -> int:
        """Re-`enqueue` jobs stuck PENDING past `min_age_s`. Returns the count
        re-driven.

        The durability net for push backends (issue #67). With `COMPUTE=poll`
        the repo *is* the queue — a PENDING row is rediscovered by the next
        `claim_next_pending`, so a lost worker self-heals. `COMPUTE=celery`
        gives that up: `enqueue()` pushes to Redis exactly once, and nothing
        re-drives a job whose push was lost — the broker was down at submit
        (see the best-effort enqueue in `job_runs`), a redis restart dropped
        the message before an AOF flush, or #62's lease reaper released a
        RUNNING job back to PENDING with no one to re-enqueue it. Any of those
        leaves a permanently-PENDING job. This pass re-pushes them.

        Idempotent with the celery path (don't double-run an in-flight job):
        - only rows still PENDING are considered — a job already claimed is
          RUNNING (or terminal) and is skipped;
        - `min_age_s` is a grace window well above normal broker pickup
          (sub-second), so a healthy just-submitted job is never re-pushed
          while its original message is still in flight; and
        - `run_job` claims via `claim_job_for_run` (PENDING-gated), so even a
          re-push that races a live delivery no-ops on the second.

        Age is measured from `state.updated_at` — the last state transition —
        so it tracks "how long stuck PENDING" for both a fresh submit and a
        reaper-released reclaim (whose `mark_pending_for_reclaim` bumps it).
        `job_types` scopes the sweep to what this deployment can actually run
        (a single all-runtimes celery pool passes its full served set); jobs
        for other runtimes are left for the pool that serves them.

        A re-enqueue that itself fails (broker still down) is logged and
        skipped — the next pass retries, so the sweep is safe to run on a
        timer regardless of broker health.
        """
        pending = self.repo.list(status=JobStatus.PENDING)
        now = utc_now()
        served = set(job_types) if job_types is not None else None
        reconciled = 0
        for record in pending:
            if served is not None and record.spec.job_type not in served:
                continue
            age_s = (now - record.state.updated_at).total_seconds()
            if age_s < min_age_s:
                continue
            job_id = str(record.spec.job_id)
            try:
                enqueue(job_id)
            except Exception:
                logger.exception(
                    "Reconciler: re-enqueue of PENDING job %s failed "
                    "(broker unavailable?); leaving PENDING for the next pass",
                    job_id,
                )
                continue
            reconciled += 1
            logger.warning(
                "Reconciler: re-enqueued PENDING job %s (age=%.0fs > %.0fs) — "
                "original push presumed lost",
                job_id, age_s, min_age_s,
            )
        return reconciled

    def list_waiting_jobs(self, job_type: str | None = None) -> list[JobRecord]:
        """List all jobs waiting for input/review."""
        return self.repo.list(status=JobStatus.WAITING_INPUT, job_type=job_type)




