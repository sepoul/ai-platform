"""Celery app + `run_job` task.

Run with:
    celery -A ai_platform.entrypoints.celery_app worker --loglevel=info

The task body mirrors `ai_platform.jobs.worker_loop._run_one_job` but
skips `claim_next_pending` — the broker already routed this specific
`job_id` to us, so we just mark it RUNNING and drive its graph.

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

from ai_platform.jobs.bootstrap import register_execution_domains
from ai_platform.jobs.job_runner import run_graph_job
from ai_platform.workspace.bootstrap import bootstrap_workspace
from ai_platform.composition_root import execution_registers_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("celery_app")


app = Celery("mathapp", broker=os.environ["CELERY_BROKER_URL"])
# Results live in Postgres via `JobRecord.state`; no Celery result_backend
# on top of that — see deployment_hetzner.md §6 "What not to do".

_workspace = None
_domains = None
WORKER_ID = "celery-unbootstrapped"


@worker_process_init.connect
def _init_worker(**_kwargs) -> None:
    global _workspace, _domains, WORKER_ID
    _workspace = bootstrap_workspace()
    # Single Celery pool registers all domains today. Per-runtime Celery
    # routing (a queue + worker pool per runtime) is future work — until
    # then this pool must run on an env that satisfies every runtime.
    _domains = register_execution_domains(execution_registers_all(), _workspace)
    WORKER_ID = f"celery-{os.getpid()}"
    logger.info("Celery worker process %s bootstrapped", WORKER_ID)


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
