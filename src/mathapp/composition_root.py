"""Single source of truth for the domains this application loads.

Domains are grouped by **worker runtime** (see
`ai_platform.jobs.runtimes`). Imports are lazy and per-runtime on
purpose: a worker provisioned for one runtime must not import another
runtime's domain modules, because those can pull a conflicting
dependency stack (the `crewai` runtime has no `logfire`; the `default`
runtime's `basic_agent` configures `logfire` at import). Importing only
the runtime's own domains keeps each worker bootable on its slimmer env.

- API process: `all_domains()` — it serves submission/result for *every*
  job type and runs on the default (logfire) env, so importing all is fine.
- A worker: `domains_for_runtime(WORKER_RUNTIME)` — only its own domains.
"""
from __future__ import annotations

from ai_platform.jobs.domain import DomainRegister
from ai_platform.jobs.runtimes import DEFAULT_RUNTIME

# Which domains live on which runtime. Keep in sync with each domain's
# JobDefinition.runtime: this controls *import* isolation (coarse,
# per-domain), while JobDefinition.runtime controls *claim* filtering
# (fine, per-job). A domain's jobs should all share one runtime.
_DOMAINS_BY_RUNTIME: dict[str, list[str]] = {
    "default": ["mathai.domain"],                       # math_qa
    "crewai": ["mathai.math_conversation.domain"],      # math_conversation
}


def _load(module_paths: list[str]) -> list[DomainRegister]:
    import importlib
    return [importlib.import_module(p).register for p in module_paths]


def domains_for_runtime(runtime: str) -> list[DomainRegister]:
    """The domain `register` callables for one worker runtime (lazy import)."""
    return _load(_DOMAINS_BY_RUNTIME.get(runtime, _DOMAINS_BY_RUNTIME[DEFAULT_RUNTIME]))


def all_domains() -> list[DomainRegister]:
    """Every domain across every runtime — for the API process."""
    paths = [p for paths in _DOMAINS_BY_RUNTIME.values() for p in paths]
    return _load(paths)
