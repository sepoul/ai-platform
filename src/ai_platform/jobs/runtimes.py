"""Worker runtimes — isolated dependency environments for job execution.

A *runtime* is a Python environment (its own venv / worker process /
container) provisioned with a specific dependency set. Some stacks
cannot coexist in one interpreter — e.g. **CrewAI** pins
`opentelemetry-sdk <1.35` while **Logfire** (our pydantic_ai tracing)
needs `>=1.39`. Rather than give up one, jobs that need a conflicting
stack run on a separate worker pool.

How it fits together:

- Runtime is scoped at the **domain** level via a single import manifest
  (`mathapp.composition_root`): runtime -> the domain modules importable
  there. That manifest is the source of truth — there is no per-job
  runtime field, because you can't read one without importing the very
  module that may crash on a slim env.
- A worker process serves exactly one runtime, chosen by the
  ``WORKER_RUNTIME`` env var. It imports/registers only that runtime's
  domains, so its job-definition set already contains *only* its jobs;
  it claims exactly those (see `ai_platform.jobs.worker_loop`). Jobs for
  other runtimes stay ``PENDING`` for the pool that can run them.
- Deployment provisions one worker pool per runtime, each from its own
  requirements file (`requirements.txt` for ``default``,
  `requirements-crewai.txt` for ``crewai``).

A domain that needs jobs on more than one runtime is split into one
domain per runtime — runtime owns the dependency stack and integration
surface; a domain just declares JobDefinitions and is assigned to a pool.

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

DEFAULT_RUNTIME = "default"
WORKER_RUNTIME_ENV = "WORKER_RUNTIME"

# runtime name -> human description (and which requirements file
# provisions it). Informational: the functional contract is the import
# manifest in composition_root + the WORKER_RUNTIME this worker serves.
RUNTIMES: dict[str, str] = {
    "default": "pydantic_ai + logfire (requirements.txt) — math_qa, API process",
    "crewai": "CrewAI panel (requirements-crewai.txt) — math_conversation; no logfire (otel-sdk <1.35)",
}


def current_worker_runtime() -> str:
    """The runtime this worker process serves (``WORKER_RUNTIME``, default 'default')."""
    return os.getenv(WORKER_RUNTIME_ENV, DEFAULT_RUNTIME).strip() or DEFAULT_RUNTIME
