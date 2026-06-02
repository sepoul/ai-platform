"""Single source of truth for the domains this application loads, split by
plane and worker runtime.

Each domain exposes two import-isolated modules:

  - `control` — builds `JobControl` (schemas only). Imported by the API for
    *every* domain; must never import the execution engine.
  - `execution` — builds `JobExecution` (the graph engine). Imported only by
    a worker whose `WORKER_RUNTIME` matches the domain's `runtime`.

Runtime is a per-domain packaging detail (import isolation is module-
granular): a worker provisioned for one runtime may lack another runtime's
deps. The API never imports execution, so it is runtime-agnostic.

- API process: `control_registers()` — all domains' control plane.
- A worker: `execution_registers_for_runtime(WORKER_RUNTIME)` — only its own.
- Celery / admin: `execution_registers_all()` — every domain's execution.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_platform.jobs.domain import ControlRegister, ExecutionRegister


@dataclass(frozen=True)
class _DomainModules:
    control: str       # module exposing register_control
    execution: str     # module exposing register_execution
    runtime: str       # which worker runtime runs this domain's jobs


_DOMAINS: list[_DomainModules] = [
    _DomainModules("mathai.math_qa.control", "mathai.math_qa.execution", "default"),
    _DomainModules(
        "mathai.math_conversation.control",
        "mathai.math_conversation.execution",
        "crewai",
    ),
]


def _control(module_path: str) -> ControlRegister:
    import importlib
    return importlib.import_module(module_path).register_control


def _execution(module_path: str) -> ExecutionRegister:
    import importlib
    return importlib.import_module(module_path).register_execution


def control_registers() -> list[ControlRegister]:
    """Every domain's control plane — for the API (engine-free, lazy import)."""
    return [_control(d.control) for d in _DOMAINS]


def execution_registers_for_runtime(runtime: str) -> list[ExecutionRegister]:
    """Execution plane for domains on `runtime` — for a worker (lazy import)."""
    return [_execution(d.execution) for d in _DOMAINS if d.runtime == runtime]


def execution_registers_all() -> list[ExecutionRegister]:
    """Every domain's execution plane — for celery / the workflow generator.

    Safe in the default runtime: building a JobExecution never imports a
    runtime-specific dep (e.g. crewai) — those imports are lazy inside nodes.
    """
    return [_execution(d.execution) for d in _DOMAINS]
