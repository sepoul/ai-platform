from __future__ import annotations

import asyncio
import logging
import traceback

from ai_platform.jobs.execution_policy import JobExecution
from ai_platform.jobs.job_runner import run_graph_job
from ai_platform.jobs.graph_execution import GraphJobExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger()


def _run_one_job(executor: GraphJobExecutor, job_definitions: dict[str, JobExecution],
                 worker_id : str, max_job_age_s: float | None = None) -> bool:
    # Claim only the job types this worker serves. The worker is handed a
    # runtime-scoped `job_definitions` (see worker.py / WORKER_RUNTIME), so
    # jobs for other runtimes stay PENDING for the pool that can run them.
    record = executor.claim_next_pending(
        job_types=list(job_definitions.keys()), worker_id=worker_id,
        max_age_s=max_job_age_s,
    )
    if record is None:
        return False

    job_id = str(record.spec.job_id)
    job_type = record.spec.job_type
    logger.info("Claimed job %s (type=%s)", job_id, job_type)

    job_def = job_definitions.get(job_type)
    if not job_def:
        logger.error("Unknown job type: %s", job_type)
        try:
            executor.fail_job(job_id, error=f"Unknown job_type: {job_type}")
        except Exception:
            logger.error("Could not mark job %s as failed", job_id)
        return True

    try:
        asyncio.run(run_graph_job(record, executor, job_def))
    except Exception:
        tb = traceback.format_exc()
        logger.error("Job %s failed:\n%s", job_id, tb)
        try:
            executor.fail_job(job_id, error=tb[:2000], retryable=True)
        except Exception:
            logger.error("Could not mark job %s as failed", job_id)

    return True
