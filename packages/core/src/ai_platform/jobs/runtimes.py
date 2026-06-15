"""Worker runtimes — isolated dependency environments for job execution.

A *runtime* is a Python environment (its own venv / worker process /
container) provisioned with a specific dependency set. Some stacks
cannot coexist in one interpreter — e.g. **CrewAI** pins
`opentelemetry-sdk <1.35` while **Logfire** (our pydantic_ai tracing)
needs `>=1.39`. Rather than give up one, jobs that need a conflicting
stack run on a separate worker pool.

How it fits together:

- Runtime is scoped at the **domain** level via a single import manifest
  (`ai_platform.composition_root`): runtime -> the domain modules importable
  there. That manifest is the source of truth — there is no per-job
  runtime field, because you can't read one without importing the very
  module that may crash on a slim env.
- A worker process serves exactly one runtime, chosen by the
  ``WORKER_RUNTIME`` env var. It imports/registers only that runtime's
  domains, so its job-definition set already contains *only* its jobs;
  it claims exactly those (see `ai_platform.jobs.worker_loop`). Jobs for
  other runtimes stay ``PENDING`` for the pool that can run them.
- Deployment provisions one worker pool per runtime. Each extra installs
  its own LLM stack on top of a shared base (``pydantic-graph``, the
  platform graph framework, plus the framework-neutral ``openai`` SDK —
  present in *both* runtimes, no otel-sdk dep so it's split-safe):
  ``packages/worker[default]`` brings
  ``pydantic-ai-slim[anthropic,duckduckgo,logfire]`` (math_qa);
  ``packages/worker[crewai]`` brings ``crewai[anthropic]`` (math_conversation,
  no Logfire — otel-sdk pin conflict). The two are mutually exclusive
  per the otel-sdk pin; per-image isolation makes ``crewai[anthropic]``
  safe (the historical clash with ``pydantic-ai-slim`` only existed when
  they shared one interpreter). See docs/control_execution_split.md.

A domain that needs jobs on more than one runtime is split into one
domain per runtime — runtime owns the dependency stack and integration
surface; a domain just declares its `JobControl` / `JobExecution` and is
assigned to a pool (see the control/execution split, docs/...).

**The load-bearing rule (narrowed).** The API never imports the engine —
it loads only `control.py` modules (`JobControl` = schemas). So the
conflict can't reach the API. But two consumers import *every* domain's
`execution.py` in one interpreter — the workflow-descriptor generator and
the (single-pool) Celery worker — so building a `JobExecution` must stay
import-safe across runtimes: heavy, runtime-specific imports (``crewai`` …)
happen **lazily inside the node body**, never at module import. Only the
``crewai`` worker imports the crew engine, and only when `RunCrewStep`
actually runs.
"""
from __future__ import annotations

import os

DEFAULT_RUNTIME = "default"
WORKER_RUNTIME_ENV = "WORKER_RUNTIME"

# runtime name -> human description (and which worker-package extra
# provisions it). Informational: the functional contract is the import
# manifest in composition_root + the WORKER_RUNTIME this worker serves.
RUNTIMES: dict[str, str] = {
    "default": "pydantic_ai + Anthropic + Logfire (packages/worker[default]) — math_qa, API process",
    "crewai":  "CrewAI[anthropic] (packages/worker[crewai]) — math_conversation; no Logfire (otel-sdk <1.35)",
}


def current_worker_runtime() -> str:
    """The runtime this worker process serves (``WORKER_RUNTIME``, default 'default')."""
    return os.getenv(WORKER_RUNTIME_ENV, DEFAULT_RUNTIME).strip() or DEFAULT_RUNTIME
