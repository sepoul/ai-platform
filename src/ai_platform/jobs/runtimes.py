"""Worker runtimes — isolated dependency environments for job execution.

A *runtime* is a Python environment (its own venv / worker process /
container) provisioned with a specific dependency set. Some stacks
cannot coexist in one interpreter — e.g. **CrewAI** pins
`opentelemetry-sdk <1.35` while **Logfire** (our pydantic_ai tracing)
needs `>=1.39`. Rather than give up one, jobs that need a conflicting
stack run on a separate worker pool.

How it fits together:

- Each `JobDefinition` declares the `runtime` it must execute on
  (default: ``"default"``).
- A worker process serves exactly one runtime, chosen by the
  ``WORKER_RUNTIME`` env var. It only *claims* jobs whose runtime
  matches; jobs for other runtimes are left ``PENDING`` for the pool
  that can run them. (See `ai_platform.jobs.worker_loop`.)
- Deployment provisions one worker pool per runtime, each from its own
  requirements file (`requirements.txt` for ``default``,
  `requirements-crewai.txt` for ``crewai``).

**Registration vs. execution — the load-bearing rule.** Building a
`JobDefinition` (and registering its domain) must stay importable from
*any* runtime, so the API and every worker can list/submit the job.
That means heavy, runtime-specific imports (``crewai`` …) must happen
**lazily inside the node body**, never at module import. The API and
the ``default`` worker import the conversation domain's JobDefinition
without ``crewai`` installed; only the ``crewai`` worker imports the
crew engine, and only when `RunCrewStep` actually runs.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_platform.jobs.execution_policy import JobDefinition

DEFAULT_RUNTIME = "default"
WORKER_RUNTIME_ENV = "WORKER_RUNTIME"

# runtime name -> human description (and which requirements file
# provisions it). Informational: the functional contract is just the
# string match between JobDefinition.runtime and WORKER_RUNTIME.
RUNTIMES: dict[str, str] = {
    "default": "pydantic_ai + logfire (requirements.txt) — math_qa, API process",
    "crewai": "CrewAI panel (requirements-crewai.txt) — math_conversation; no logfire (otel-sdk <1.35)",
}


def current_worker_runtime() -> str:
    """The runtime this worker process serves (``WORKER_RUNTIME``, default 'default')."""
    return os.getenv(WORKER_RUNTIME_ENV, DEFAULT_RUNTIME).strip() or DEFAULT_RUNTIME


def select_for_runtime(
    job_definitions: dict[str, "JobDefinition"], runtime: str
) -> dict[str, "JobDefinition"]:
    """Subset of `job_definitions` whose declared runtime matches `runtime`."""
    return {
        name: jd
        for name, jd in job_definitions.items()
        if getattr(jd, "runtime", DEFAULT_RUNTIME) == runtime
    }
