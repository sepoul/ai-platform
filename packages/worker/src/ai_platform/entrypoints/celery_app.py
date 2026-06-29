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
        record = executor.mark_running(job_id, worker_id=WORKER_ID)
    except Exception:
        logger.exception("Could not mark job %s as running", job_id)
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
