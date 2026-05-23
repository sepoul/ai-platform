"""Single source of truth for the domains this application loads, and the
worker runtime each runs on.

Runtime is scoped at the **domain** level: the map below — runtime ->
domain modules — is the one authoritative declaration. There is no
per-job runtime field, because a worker can't read one without importing
the very module that may crash on its slim env (the `crewai` image has
no `logfire`; `mathai.domain` pulls `basic_agent`, which configures
`logfire` at import). So the map does double duty:

  1. **Import isolation.** A worker imports only its runtime's domains,
     so a slim env without another runtime's deps still boots.
  2. **Job routing.** Because it imported only its own domains, the
     worker's registered job set already contains *only* its jobs — it
     claims exactly those; other runtimes' jobs stay PENDING for their
     pool. No separate per-job filter needed.

A domain that needs to span runtimes is split into one domain per
runtime. Runtime owns the dependency stack; a domain just declares jobs.

- A worker: `domains_for_runtime(WORKER_RUNTIME)` — only its own domains.
- API / celery: `all_domains()` — every job type, for submission/result.

  TODO(api-runtime-decoupling): the API importing *all* domains is the
  one thing forcing the "load-bearing rule" (heavy imports stay lazy
  inside node bodies) — see ai_platform.jobs.runtimes. The API only
  needs each job's *schemas* (submit/result), not its execution code,
  so it shouldn't have to care about runtime at all. Flagged for later;
  not addressed here.
"""
from __future__ import annotations

from ai_platform.jobs.domain import DomainRegister
from ai_platform.jobs.runtimes import DEFAULT_RUNTIME

# runtime -> domain modules that run on it. The single source of truth
# for both import isolation and job routing (see module docstring).
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
