"""Single source of truth for the domains this application loads.

Runtime selection is **per job**: each `JobDefinition` declares the
`runtime` it needs, and `select_for_runtime` (in
`ai_platform.jobs.runtimes`) filters claims by it. A domain is free to
register jobs across *several* runtimes — runtime is a property of the
job, not the domain.

The map below is a different, lower-level thing: an **import manifest**.
Import isolation is module-granular and a pure packaging detail — a
worker provisioned for one runtime may lack another runtime's deps (the
`crewai` image has no `logfire`; `mathai.domain` pulls `basic_agent`,
which configures `logfire` at import). So a worker must know, *without
importing*, which registration modules are safe to import under its
runtime. That's all this manifest encodes: runtime -> registration
modules importable there. It is not a domain→runtime coupling — one
domain may appear under multiple runtimes (list its import-safe
registration module under each), and the authoritative routing still
comes from each job's `JobDefinition.runtime`.

- API process: `all_domains()` — it serves submission/result for *every*
  job type and runs on the default (logfire) env, so importing all is fine.
- A worker: `domains_for_runtime(WORKER_RUNTIME)` — only the modules safe
  to import there; per-job claim filtering then narrows to its runtime.
"""
from __future__ import annotations

from ai_platform.jobs.domain import DomainRegister
from ai_platform.jobs.runtimes import DEFAULT_RUNTIME

# Import manifest: runtime -> registration modules importable under it.
# Packaging detail only (see module docstring). The authoritative
# job→runtime routing lives in each JobDefinition.runtime + select_for_runtime.
# A domain spanning runtimes lists an import-safe registration module under
# each runtime; today each of ours happens to be 1:1.
_IMPORTABLE_DOMAINS_BY_RUNTIME: dict[str, list[str]] = {
    "default": ["mathai.domain"],                       # math_qa
    "crewai": ["mathai.math_conversation.domain"],      # math_conversation
}


def _load(module_paths: list[str]) -> list[DomainRegister]:
    import importlib
    return [importlib.import_module(p).register for p in module_paths]


def domains_for_runtime(runtime: str) -> list[DomainRegister]:
    """Registration callables whose modules are import-safe on `runtime` (lazy import)."""
    return _load(
        _IMPORTABLE_DOMAINS_BY_RUNTIME.get(
            runtime, _IMPORTABLE_DOMAINS_BY_RUNTIME[DEFAULT_RUNTIME]
        )
    )


def all_domains() -> list[DomainRegister]:
    """Every domain across every runtime — for the API process."""
    seen: set[str] = set()
    paths: list[str] = []
    for module_paths in _IMPORTABLE_DOMAINS_BY_RUNTIME.values():
        for p in module_paths:
            if p not in seen:  # a domain may appear under multiple runtimes
                seen.add(p)
                paths.append(p)
    return _load(paths)
