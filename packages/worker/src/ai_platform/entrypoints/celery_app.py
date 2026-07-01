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

Two boot hooks, split by what they touch (issue #73):

- `worker_init` (main process, once, BEFORE the fork) installs this
  runtime's CodePackages. pip mutates the shared `site-packages`, so it
  must run exactly once: the old wiring ran it per child, so with
  `CELERY_CONCURRENCY=N` all N children pip-installed the same wheels into
  the same dir concurrently — corrupting each other (the `google/_upb/`
  missing-file error) and leaving children serving inconsistent domain
  sets. The transient DB pool it opens to read the catalog is closed before
  returning, so no socket is inherited across the fork (see below).
- `worker_process_init` (per prefork child) opens that child's own psycopg
  pool and registers this runtime's domains by importing the now-installed
  wheels off disk. It must stay per-child — celery's prefork pool would
  otherwise inherit the master's psycopg connections across the fork; those
  file descriptors aren't safe to share, and the first task on each child
  hangs on `pool.getconn` until it times out after 30s. It no longer
  installs anything.

Durability net (issue #67). Under `COMPUTE=poll` the repo *is* the queue,
so a lost worker self-heals on the next `SELECT`. Celery gives that up —
`enqueue()` pushes to Redis once and nothing re-drives a job whose push was
lost (broker down at submit, redis restart before an AOF flush, or #62's
lease reaper releasing a RUNNING job back to PENDING). The `reconcile_jobs`
beat task below restores the safety net: each tick it reaps expired leases
(RUNNING→PENDING) and re-enqueues jobs stuck PENDING past a grace window —
through this pool's per-runtime queue, scoped to its own runtime (issue #66).
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
from celery.signals import worker_init, worker_process_init

from ai_platform.compute.celery import celery_queue_for_runtime
from ai_platform.jobs.bootstrap import register_execution_domains
from ai_platform.jobs.code_package_install import install_packages_for_runtime
from ai_platform.jobs.code_package_service import CodePackageService
from ai_platform.jobs.job_runner import run_graph_job
from ai_platform.jobs.runtimes import current_worker_runtime
from ai_platform.workspace.bootstrap import bootstrap_workspace
from ai_platform.workspace.storage.backends import make_backend
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


@worker_init.connect
def _install_runtime_packages(**_kwargs) -> None:
    """Install this runtime's CodePackages ONCE in the worker's main process,
    before the prefork pool forks children (issue #73).

    pip installs into the interpreter's shared `site-packages`. The old wiring
    ran this inside `worker_process_init`, so with `CELERY_CONCURRENCY=N` all N
    children pip-installed the same wheels into the same dir concurrently —
    corrupting each other (`OSError ... google/_upb/`) and leaving children
    serving different domain sets. Hoisting it to `worker_init` (main process,
    pre-fork) makes it happen exactly once; each child then imports the landed
    wheels off disk when it registers domains in `worker_process_init`.

    Best-effort + idempotent, like the poll worker (entrypoints/worker.py):
    already-installed wheels short-circuit before any pip call, and a failed
    install logs + continues — the worker still serves the JobDefinitions baked
    into its image.

    Fork-safety: this opens a transient backend purely to read the CodePackage
    catalog, then CLOSES its psycopg pool before returning. An open pool here
    would be inherited across the fork and hang the children on first checkout —
    the exact reason the per-child bootstrap in `worker_process_init` exists
    (see the module docstring). The main process never runs jobs, so it has no
    further use for the pool.
    """
    backend = make_backend()
    try:
        service = CodePackageService(backend.code_package_repo, backend.file_repo)
        installed = install_packages_for_runtime(RUNTIME, service)
        if installed:
            logger.info(
                "Installed %d CodePackage(s) at boot (runtime=%s): %s",
                len(installed), RUNTIME, installed,
            )
    finally:
        # Release the catalog pool's connection FDs before the fork. Backends
        # without a DB pool (local / b2) expose no `_pool`, so this is a no-op
        # there; only the supabase backend opens one.
        pool = getattr(backend, "_pool", None)
        if pool is not None:
            try:
                pool.close()
            except Exception:  # noqa: BLE001 — best-effort teardown
                logger.exception("Failed to close boot-time catalog pool")


@worker_process_init.connect
def _init_worker(**_kwargs) -> None:
    global _workspace, _domains, WORKER_ID
    _workspace = bootstrap_workspace()

    # Scope registration to this pool's runtime, exactly like the poll worker
    # (entrypoints/worker.py): discover its domains from the JobDefinition
    # catalog (hardcoded `_DOMAINS` fallback for cold boot) and register ONLY
    # that runtime's domains; the broker only ever hands it that runtime's
    # queue. The CodePackage wheels these imports resolve were already installed
    # ONCE in the main process by `_install_runtime_packages` (`worker_init`,
    # pre-fork) — NOT here, where N children would race pip on the same
    # site-packages (issue #73). This handler opens this child's own psycopg
    # pool (`bootstrap_workspace`), which is why it must stay per-child.
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


# ---------------------------------------------------------------------------
# Wedge guards (issue #79) — defense-in-depth for a non-compose launch.
# ---------------------------------------------------------------------------
# These mirror the docker-compose `command:` flags (-B --time-limit
# --soft-time-limit --prefetch-multiplier). Prod's deployed image PREDATES
# these, so at the COMPUTE=celery cutover the **compose flags** are what take
# effect; these app.conf defaults land on the next image rebuild (they only
# matter for a bare `celery … worker` with no CLI flags).
#
# A soft limit raises a Python exception that CANNOT fire while a thread is
# blocked in the C-level psycopg wait (the exact stale-pooler wedge #79
# addresses); only the hard `task_time_limit` (SIGKILL + child recycle)
# interrupts it. Tuning: `task_time_limit` must exceed the longest *legitimate
# total* job runtime — the 900s lease TTL covers per-step gaps, not the whole
# job — so raise both if a real job can legitimately run longer.
app.conf.task_time_limit = _env_float("CELERY_TASK_TIME_LIMIT_S", 900)
app.conf.task_soft_time_limit = _env_float("CELERY_TASK_SOFT_TIME_LIMIT_S", 840)
# A wedged prefork child must not sit on prefetched jobs behind it, and a job
# killed by the hard limit (or a died child) must redeliver, not vanish.
app.conf.worker_prefetch_multiplier = 1
app.conf.task_acks_late = True


def _reenqueue_for_runtime(job_id: str) -> None:
    """Re-push a stuck-PENDING job through the SAME per-runtime routing the API
    producer uses (issue #66), mirroring `CeleryComputeBackend.enqueue`.

    This pool only reconciles its own runtime's job_types (`reconcile_jobs`
    passes `job_types=served`), so a re-driven job always belongs on THIS
    runtime's queue. Route there explicitly with `apply_async(queue=...)`
    rather than leaning on the implicit `task_default_queue` — same as the
    producer, and robust if the default queue ever changes. The crewai pool's
    reconciler therefore re-pushes only crewai jobs onto `runtime.crewai`, the
    default pool only default jobs onto `runtime.default`; neither re-drives
    the other's jobs, so cross-runtime jobs are never misrouted.
    """
    run_job.apply_async(args=[job_id], queue=celery_queue_for_runtime(RUNTIME))


@app.task(name="reconcile_jobs")
def reconcile_jobs() -> None:
    """Beat-scheduled durability sweep — the celery analogue of the poll
    loop's idle-tick reap (issue #67).

    Two passes, in order:
    1. Reap expired leases (RUNNING→PENDING for re-claim, or FAILED once
       `max_attempts` is used) — the same `reclaim_expired_leases` the poll
       worker runs, but celery has no poll loop to host it.
    2. Reconcile PENDING jobs — re-enqueue any stuck PENDING past the grace
       window (lost push at submit, redis restart, or a job the reaper just
       released) through this pool's per-runtime queue
       (`_reenqueue_for_runtime`). `run_job`'s PENDING-gated claim makes the
       re-delivery idempotent.

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
        # Scope the sweep to THIS pool's runtime job_types (runtime-scoped
        # `_domains`, issue #66) and re-push through this runtime's queue.
        # Other runtimes' PENDING jobs are left for their own pool's reconciler.
        served = list(_domains.job_executions.keys())
        n = executor.reconcile_pending_jobs(
            _reenqueue_for_runtime, PENDING_RECONCILE_AGE_S, job_types=served,
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
