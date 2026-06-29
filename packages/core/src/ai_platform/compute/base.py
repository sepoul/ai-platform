"""ComputeBackend protocol — the seam.

Two methods, with very different semantics depending on the backend:

- `enqueue(job_id)` is called by the API right after a `JobRecord`
  is persisted (or after `/review` flips a paused job back to
  PENDING). Backends that own a queue (Celery, SQS) push the work
  there; pure-poll backends do nothing because workers will discover
  the record on their next tick.

- `start_worker(...)` is the long-running consumer. Poll backends
  own the loop here. Backends that have their own worker CLI
  (Celery's `celery worker`) raise `NotImplementedError` so the
  operator sees a clear "use the right entrypoint" message instead
  of a silently-empty process.
"""
from __future__ import annotations

from typing import Callable, Protocol

from ai_platform.jobs.execution_policy import JobExecution
from ai_platform.jobs.graph_execution import GraphJobExecutor


class EnqueueUnavailable(Exception):
    """A push backend's `enqueue` could not reach the broker (down /
    restarting) — a *transient* failure (issue #72).

    The job is already durably persisted PENDING, so the API's best-effort
    enqueue swallows exactly this and leaves the reconciler to re-drive it
    (issue #67). It is deliberately narrow: a *producer misconfiguration*
    (bad/missing `CELERY_BROKER_URL`, an import or routing error) is NOT this
    — those must surface, not hide as a silent permanent PENDING. So a backend
    raises `EnqueueUnavailable` only for genuine broker-unavailability and lets
    every other error propagate unwrapped.
    """


class ComputeBackend(Protocol):
    name: str

    def enqueue(self, job_id: str) -> None: ...

    def start_worker(
        self,
        *,
        worker_id: str,
        interval_s: int = 5,
        once: bool = False,
        should_stop: Callable[[], bool] = lambda: False,
        max_job_age_s: float | None = None,
        job_lease_ttl_s: float | None = None,
    ) -> None: ...


# Type alias for callers that need the wired pieces, mostly internal.
WiredCompute = tuple[GraphJobExecutor, dict[str, JobExecution]]
