"""End-to-end broker test for `COMPUTE=celery` (issue #65 / epic #64).

Proves the *broker path* — submit → `enqueue()` → Redis → `celery-worker`
→ `SUCCEEDED` — actually drives a job to completion, so the wiring goes
red the moment any link in that chain breaks (a botched task signature,
a bootstrap regression, a producer that can't `send_task("run_job", …)`
through the broker). `enqueue` publishes by task name from a producer-side
Celery app, never importing the worker's task module (issue #72), so this
also covers the split-image producer path end-to-end.

How it stays honest:

* It runs against `BACKEND=local` in a throwaway data dir and spawns its
  **own** `celery -A ai_platform.entrypoints.celery_app worker`
  subprocess pointed at the same dir + broker. **No poll worker is ever
  started** — nothing but the Celery consumer can move the job — so a
  `SUCCEEDED` status is proof the broker drove it, not a `SELECT` loop.
* The job is the synthetic `_demo` echo (no LLM, no network), so the
  test is deterministic and offline.
* Per-runtime queues (issue #66): `_demo` is a `default`-runtime job, so
  `enqueue` routes it to the `runtime.default` queue, and the worker is
  spawned with `WORKER_RUNTIME=default` — i.e. the `celery-worker`
  consumer from compose, which consumes exactly that queue. (The crewai
  pool consumes `runtime.crewai`; its routing is unit-covered in
  `test_celery_routing.py`. This e2e exercises the default lane through a
  real broker.)

Gating: skipped unless a Redis broker is reachable at `CELERY_BROKER_URL`
(default `redis://localhost:6379/0`). On a host with no Redis the connect
fails fast (connection-refused) and the module skips, so the normal
`pytest tests` run stays green and fast. `scripts/test-celery.sh` brings
up a throwaway Redis and runs this, which is the wired make/script target.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# `celery_app` reads CELERY_BROKER_URL at import; default it to localhost so
# importing the module (and the reachability probe below) never KeyErrors.
BROKER_URL = os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")

from ai_platform.entrypoints.celery_app import app as celery_app  # noqa: E402


def _broker_reachable(timeout: float = 2.0) -> bool:
    """True if the Celery broker (Redis) accepts a connection right now.

    `max_retries=0` → a single attempt with no backoff, so a host with no
    Redis skips near-instantly (connection-refused) instead of waiting out
    kombu's default retry interval.
    """
    try:
        conn = celery_app.connection()
        conn.ensure_connection(max_retries=0, timeout=timeout)
        conn.release()
        return True
    except Exception:
        return False


if not _broker_reachable():
    pytest.skip(
        f"Celery broker not reachable at {BROKER_URL} — start one with "
        f"scripts/test-celery.sh (brings up a throwaway redis).",
        allow_module_level=True,
    )


def _spawn_celery_worker(data_dir: str) -> subprocess.Popen:
    """Start a real celery worker subprocess bound to `data_dir` + broker.

    PYTHONPATH mirrors this process's `sys.path` so the child resolves the
    exact same `ai_platform` / `aiplatform_demo` source roots pytest set up
    (the workspace isn't pip-installed — it's discovered via `pythonpath`).
    """
    env = dict(os.environ)
    env["BACKEND"] = "local"
    env["LOCAL_DATA_DIR"] = data_dir
    env["CELERY_BROKER_URL"] = BROKER_URL
    # The default-runtime consumer: registers default-runtime domains
    # (`_demo`) and consumes `runtime.default` (its WORKER_RUNTIME-derived
    # task_default_queue) — exactly the `celery-worker` compose service.
    env["WORKER_RUNTIME"] = "default"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    # macOS prefork fork-safety guard — harmless on Linux/CI.
    env.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
    return subprocess.Popen(
        [
            sys.executable, "-m", "celery",
            "-A", "ai_platform.entrypoints.celery_app", "worker",
            "--loglevel=info",
            "--concurrency=1",
            "-n", "celery-e2e@%h",
        ],
        env=env,
    )


def _wait_for_worker_online(deadline_s: float = 30.0) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            if celery_app.control.ping(timeout=1.0):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _wait_for_terminal(executor, job_id: str, deadline_s: float = 60.0):
    from ai_platform.workspace.storage.structured.job_repository import JobStatus

    terminal = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)
    end = time.time() + deadline_s
    while time.time() < end:
        status = executor.repo.get(job_id).state.status
        if status in terminal:
            return status
        time.sleep(0.5)
    return executor.repo.get(job_id).state.status


def test_demo_job_reaches_succeeded_via_broker(tmp_path: Path):
    os.environ["BACKEND"] = "local"
    os.environ["LOCAL_DATA_DIR"] = str(tmp_path)

    from ai_platform.compute.celery import CeleryComputeBackend
    from ai_platform.composition_root import execution_registers_for_runtime
    from ai_platform.jobs.bootstrap import register_execution_domains
    from ai_platform.jobs.runtimes import DEFAULT_RUNTIME
    from ai_platform.workspace.bootstrap import bootstrap_workspace
    from ai_platform.workspace.storage.structured.job_repository import JobStatus

    # Bootstrap the default runtime exactly like the `celery-worker` pool
    # does, so the job we submit is shaped like a real `/jobs/runs/submit`.
    ws = bootstrap_workspace()
    domains = register_execution_domains(
        execution_registers_for_runtime(DEFAULT_RUNTIME), ws
    )
    assert "demo" in domains.job_executions, "demo execution must be registered"

    worker = _spawn_celery_worker(str(tmp_path))
    try:
        assert _wait_for_worker_online(), "celery worker did not come online"

        record = ws.executor.submit_graph_job(
            job_type="demo",
            graph_ref="demo_echo",
            initial_state={},
            deps_payload={"message": "hello via the broker"},
        )
        job_id = str(record.spec.job_id)
        # Submitted, but NOT running — nothing has touched it yet.
        assert record.state.status == JobStatus.PENDING

        # The one and only delivery mechanism: enqueue → Redis → worker.
        # No runtime resolver wired → routes to the `runtime.default` queue,
        # which the WORKER_RUNTIME=default consumer above is draining.
        CeleryComputeBackend(ws.executor, domains.job_executions).enqueue(job_id)

        status = _wait_for_terminal(ws.executor, job_id)
        assert status == JobStatus.SUCCEEDED, (
            f"job {job_id} ended {status}, expected SUCCEEDED (the celery "
            f"consumer should have driven it — no poll worker was running)"
        )
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=5)
