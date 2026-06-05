"""Worker process: delegates the run loop to the configured ComputeBackend.

The loop body lives on the backend (`PollingComputeBackend.start_worker`)
because the same seam needs to support backends with no separate worker
at all (`ThreadComputeBackend`) or their own CLI (`CeleryComputeBackend`).

Usage:
    python -m ai_platform.entrypoints.worker                # COMPUTE=poll, interval=10s
    python -m ai_platform.entrypoints.worker --interval 5
    python -m ai_platform.entrypoints.worker --once         # run one job then exit
"""
from __future__ import annotations

import logging
import os
import signal
from argparse import ArgumentParser

from ai_platform.compute.bootstrap import bootstrap_compute
from ai_platform.jobs.bootstrap import register_execution_domains
from ai_platform.jobs.code_package_install import install_packages_for_runtime
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

    # Friend-test path: pull any CodePackages registered for this runtime
    # (via `POST /code-packages`) and pip-install them before we resolve
    # execution registers. Idempotent + best-effort — already-installed
    # rows skip, failures log + continue, the worker still serves the
    # JobDefinitions whose code is baked into the image.
    installed = install_packages_for_runtime(runtime, ws.code_package_service)
    if installed:
        logger.info("Installed %d CodePackage(s) at boot: %s", len(installed), installed)

    # Catalog-driven discovery: JobDefinition.code_entrypoint per row
    # (filtered to this runtime, deduped). Drops the dependency on
    # composition_root._DOMAINS for the friend-test path. The hardcoded
    # fallback covers cold boot (empty catalog) so a fresh deploy still
    # serves the platform's baseline domains.
    registers = execution_registers_from_catalog(ws.job_definition_service, runtime)
    if not registers:
        logger.info(
            "execution_registers_from_catalog returned empty for runtime=%s — "
            "falling back to hardcoded _DOMAINS for cold boot",
            runtime,
        )
        registers = execution_registers_for_runtime(runtime)

    domains = register_execution_domains(registers, ws)
    served = domains.job_executions
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
