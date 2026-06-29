"""Celery app + `run_job` task.

Run with:
    celery -A ai_platform.entrypoints.celery_app worker --loglevel=info

The task body mirrors `ai_platform.jobs.worker_loop._run_one_job` but
skips `claim_next_pending` — the broker already routed this specific
`job_id` to us, so we just mark it RUNNING and drive its graph.

**Per-runtime scope (issue #66).** Like the poll worker
(`entrypoints/worker.py`), this pool serves exactly one runtime
(`WORKER_RUNTIME`, default "default"): it registers only that runtime's
domains and consumes only that runtime's queue
(`celery_queue_for_runtime`). The API producer routes each job to its
runtime's queue, so a slim env (e.g. the `crewai` pool, missing the
pydantic_ai stack) never receives a job it can't import. Deploy one
consumer per runtime (`celery-worker` / `celery-worker-crewai`), each
with the matching `WORKER_RUNTIME`.

Bootstrap runs in `worker_process_init`, NOT at module import. Celery's
prefork pool would otherwise inherit the master's psycopg connections
across the fork; those file descriptors aren't safe to share, and the
first task on each child hangs on `pool.getconn` until it times out
after 30s. Initialising per-child gives each worker its own pool.

Durability net (issue #67). Under `COMPUTE=poll` the repo *is* the queue,
so a lost worker self-heals on the next `SELECT`. Celery gives that up —
`enqueue()` pushes to Redis once and nothing re-drives a job whose push was
lost (broker down at submit, redis restart before an AOF flush, or #62's
lease reaper releasing a RUNNING job back to PENDING). The `reconcile_jobs`
beat task below restores the safety net: each tick it reaps expired leases
(RUNNING→PENDING) and re-`delay`s jobs stuck PENDING past a grace window.
It only fires when a beat scheduler runs — embed it with `celery … worker
-B` or run a dedicated `celery … beat`; the reaper half additionally needs
`WORKER_JOB_LEASE_TTL_S`. See docs/reference/compute-backends.md.
"""
from __future__ import annotations

import asyncio
import logging
import os
import traceback

from celery import Celery
from celery.signals import worker_process_init

from ai_platform.compute.celery import celery_queue_for_runtime
from ai_platform.jobs.bootstrap import register_execution_domains
from ai_platform.jobs.code_package_install import install_packages_for_runtime
from ai_platform.jobs.job_runner import run_graph_job
from ai_platform.jobs.runtimes import current_worker_runtime
from ai_platform.workspace.bootstrap import bootstrap_workspace
from ai_platform.composition_root import (
    execution_registers_for_runtime,
    execution_registers_from_catalog,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("celery_app")


app = Celery("mathapp", broker=os.environ["CELERY_BROKER_URL"])
# Results live in Postgres via `JobRecord.state`; no Celery result_backend
# on top of that — see deployment_hetzner.md §6 "What not to do".

# This pool serves exactly one runtime and consumes only its queue. A worker
# started without an explicit `-Q` consumes `task_default_queue`, so deriving
# it from `WORKER_RUNTIME` is all it takes to scope consumption — the API
# producer routes with an explicit `queue=` regardless (CeleryComputeBackend).
RUNTIME = current_worker_runtime()
app.conf.task_default_queue = celery_queue_for_runtime(RUNTIME)

_workspace = None
_domains = None
WORKER_ID = "celery-unbootstrapped"


@worker_process_init.connect
def _init_worker(**_kwargs) -> None:
    global _workspace, _domains, WORKER_ID
    _workspace = bootstrap_workspace()

    # Scope registration to this pool's runtime, exactly like the poll worker
    # (entrypoints/worker.py): install any CodePackages deployed for the
    # runtime, then discover its domains from the JobDefinition catalog
    # (hardcoded `_DOMAINS` fallback for cold boot). The pool registers ONLY
    # its runtime's domains; the broker only ever hands it that runtime's
    # queue. The install pass runs per forked child — best-effort + idempotent
    # (already-installed wheels short-circuit before any pip call).
    installed = install_packages_for_runtime(RUNTIME, _workspace.code_package_service)
    if installed:
        logger.info("Installed %d CodePackage(s) at boot: %s", len(installed), installed)

    registers = execution_registers_from_catalog(
        _workspace.job_definition_service, RUNTIME
    )
    if not registers:
        registers = execution_registers_for_runtime(RUNTIME)

    _domains = register_execution_domains(registers, _workspace)
    WORKER_ID = f"celery-{os.getpid()}"
    logger.info(
        "Celery worker process %s bootstrapped (runtime=%s, queue=%s) serving: %s",
        WORKER_ID, RUNTIME, app.conf.task_default_queue,
        sorted(_domains.job_executions.keys()) or "(none)",
    )


@app.task(name="run_job")
def run_job(job_id: str) -> None:
    assert _workspace is not None and _domains is not None, (
        "Celery worker not bootstrapped — worker_process_init never fired"
    )
    executor = _workspace.executor
    job_def_map = _domains.job_executions

    try:
        record = executor.claim_job_for_run(job_id, worker_id=WORKER_ID)
    except Exception:
        logger.exception("Could not mark job %s as running", job_id)
        return

    # Idempotency guard for the durability net (issue #67): the PENDING
    # reconciler re-`delay`s jobs whose original push was lost, so this
    # task can be delivered the same job_id more than once. `claim_job_for_run`
    # only transitions a still-PENDING row to RUNNING; a duplicate delivery
    # for an already-claimed/finished job returns None and is dropped here
    # instead of running the job a second time.
    if record is None:
        logger.info(
            "Celery: job %s is no longer PENDING (already claimed or finished) "
            "— skipping duplicate delivery", job_id,
        )
        return

    job_type = record.spec.job_type
    logger.info("Celery picked up job %s (type=%s)", job_id, job_type)

    job_def = job_def_map.get(job_type)
    if job_def is None:
        logger.error("Unknown job type: %s", job_type)
        try:
            executor.fail_job(job_id, error=f"Unknown job_type: {job_type}")
        except Exception:
            logger.exception("Could not mark job %s as failed", job_id)
        return

    try:
        asyncio.run(run_graph_job(record, executor, job_def))
    except Exception:
        tb = traceback.format_exc()
        logger.error("Job %s failed:\n%s", job_id, tb)
        try:
            executor.fail_job(job_id, error=tb[:2000], retryable=True)
        except Exception:
            logger.exception("Could not mark job %s as failed", job_id)


# ---------------------------------------------------------------------------
# Durability net: PENDING reconciler + lease reaper (issue #67)
# ---------------------------------------------------------------------------

def _env_float(name: str, default: float | None = None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return float(raw)


# How often beat fires the reconcile/reap pass.
RECONCILE_INTERVAL_S = _env_float("CELERY_RECONCILE_INTERVAL_S", 60.0)
# A job must sit PENDING at least this long before it's presumed a lost push
# and re-`delay`d — comfortably above normal broker pickup (sub-second), so a
# healthy just-submitted job is never re-driven while its message is in flight.
PENDING_RECONCILE_AGE_S = _env_float("CELERY_PENDING_RECONCILE_AGE_S", 120.0)
# Reuse #62's lease TTL: under poll the poll loop reaps; under celery there is
# no poll loop, so the beat task carries the reaper too. Unset = reaper off.
JOB_LEASE_TTL_S = _env_float("WORKER_JOB_LEASE_TTL_S")


@app.task(name="reconcile_jobs")
def reconcile_jobs() -> None:
    """Beat-scheduled durability sweep — the celery analogue of the poll
    loop's idle-tick reap (issue #67).

    Two passes, in order:
    1. Reap expired leases (RUNNING→PENDING for re-claim, or FAILED once
       `max_attempts` is used) — the same `reclaim_expired_leases` the poll
       worker runs, but celery has no poll loop to host it.
    2. Reconcile PENDING jobs — re-`delay` any stuck PENDING past the grace
       window (lost push at submit, redis restart, or a job the reaper just
       released). `run_job`'s PENDING-gated claim makes the re-delivery
       idempotent.

    Reap first so a freshly-reclaimed job is PENDING for a *later* tick to
    re-enqueue (it won't be re-pushed this tick — its `updated_at` was just
    bumped, so it's inside the grace window). Best-effort: this runs in a
    bootstrapped worker child, and any error is logged, never raised, so a
    flaky pass doesn't poison the beat schedule.
    """
    if _workspace is None or _domains is None:
        # Defensive: the task body runs in a worker child, which is
        # bootstrapped by `worker_process_init`. If somehow not, skip quietly.
        logger.warning("reconcile_jobs fired before bootstrap — skipping")
        return

    executor = _workspace.executor

    if JOB_LEASE_TTL_S is not None:
        try:
            reaped = executor.reclaim_expired_leases(JOB_LEASE_TTL_S)
            if reaped:
                logger.info("Reconciler: reclaimed %d expired-lease job(s)", reaped)
        except Exception:
            logger.exception("Reconciler: lease reap pass failed; continuing")

    try:
        served = list(_domains.job_executions.keys())
        n = executor.reconcile_pending_jobs(
            run_job.delay, PENDING_RECONCILE_AGE_S, job_types=served,
        )
        if n:
            logger.info("Reconciler: re-enqueued %d stuck-PENDING job(s)", n)
    except Exception:
        logger.exception("Reconciler: pending reconcile pass failed; continuing")


@app.on_after_configure.connect
def _register_periodic(sender, **_kwargs) -> None:
    """Register the durability sweep on beat. The whole sweep is inert unless a
    beat scheduler is actually running (`celery … worker -B` or a dedicated
    `celery … beat`) — a default deploy that only runs `celery … worker` never
    fires it. When beat *is* on, the reconcile pass runs with its defaults; the
    reaper pass within it stays off until `WORKER_JOB_LEASE_TTL_S` is set.
    Registration itself is unconditional + cheap."""
    sender.add_periodic_task(
        RECONCILE_INTERVAL_S,
        reconcile_jobs.s(),
        name="reconcile-pending-and-reap",
    )
