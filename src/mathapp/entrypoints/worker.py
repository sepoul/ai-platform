"""Worker process: delegates the run loop to the configured ComputeBackend.

The loop body lives on the backend (`PollingComputeBackend.start_worker`)
because the same seam needs to support backends with no separate worker
at all (`ThreadComputeBackend`) or their own CLI (`CeleryComputeBackend`).

Usage:
    python -m mathapp.entrypoints.worker                # COMPUTE=poll, interval=10s
    python -m mathapp.entrypoints.worker --interval 5
    python -m mathapp.entrypoints.worker --once         # run one job then exit
"""
from __future__ import annotations

import logging
import os
import signal
from argparse import ArgumentParser

from ai_platform.compute.bootstrap import bootstrap_compute
from ai_platform.jobs.bootstrap import register_domains
from ai_platform.jobs.runtimes import current_worker_runtime
from ai_platform.workspace.bootstrap import bootstrap_workspace
from mathapp.composition_root import domains_for_runtime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")

WORKER_ID = f"worker-{os.getpid()}"


_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    logger.info("Received signal %s — finishing current job then exiting", signum)
    _shutdown = True


def main():
    parser = ArgumentParser(description="Job worker")
    parser.add_argument("--interval", type=int, default=10, help="Poll interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run one job then exit")
    parser.add_argument(
        "--max-job-age",
        type=float,
        default=_env_float("WORKER_MAX_JOB_AGE_S"),
        help=(
            "Ignore PENDING jobs whose created_at is older than this many seconds. "
            "Default: env WORKER_MAX_JOB_AGE_S, else unlimited. Poll backend only — "
            "Celery/Thread deliver via broker so stale rows never reach the worker."
        ),
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    ws = bootstrap_workspace()

    # Scope this worker to its runtime: import + register only this
    # runtime's domains (so a slim env without the other runtime's deps
    # still boots). The registered set is therefore already only this
    # runtime's jobs — the worker claims exactly those, leaving other
    # runtimes' jobs PENDING for the pool provisioned with that stack.
    runtime = current_worker_runtime()
    domains = register_domains(domains_for_runtime(runtime), ws)
    served = {name: jd.execution for name, jd in domains.job_definitions.items()}
    logger.info(
        "Worker %s runtime=%s serving job types: %s",
        WORKER_ID, runtime, sorted(served.keys()) or "(none)",
    )

    compute = bootstrap_compute(ws.executor, served)
    logger.info("Worker %s using compute=%s", WORKER_ID, compute.name)

    compute.start_worker(
        worker_id=WORKER_ID,
        interval_s=args.interval,
        once=args.once,
        should_stop=lambda: _shutdown,
        max_job_age_s=args.max_job_age,
    )


def _env_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    return float(raw)


if __name__ == "__main__":
    main()
