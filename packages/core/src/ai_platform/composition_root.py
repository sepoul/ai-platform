"""Discovery of the domains this application loads, split by plane + runtime.

Each domain exposes two import-isolated modules:

  - `control` — builds `JobControl` (schemas only). Imported by the API for
    *every* domain; must never import the execution engine.
  - `execution` — builds `JobExecution` (the graph engine). Imported only by
    a worker whose `WORKER_RUNTIME` matches the domain's `runtime`.

Runtime is a per-domain packaging detail (import isolation is module-
granular): a worker provisioned for one runtime may lack another runtime's
deps. The API never imports execution, so it is runtime-agnostic.

**Two discovery paths.** The primary one is *catalog-driven*: read
JobDefinition rows and derive the import list from their
`control_entrypoint` / `code_entrypoint` fields. This is what makes
the friend-test work — deploying a new domain via `aiplatform deploy`
is the *only* action needed; no edit to this file. Helpers:

- `control_registers_from_catalog(jd_service)` — API process.
- `execution_registers_from_catalog(jd_service, runtime)` — a worker.

The legacy *hardcoded* path remains as a cold-boot fallback (DB
down, fresh box with empty catalog before any deploy). It's a list
of named platform domains the entry point can fall back on:

- `control_registers()` — every entry in `_DOMAINS`.
- `execution_registers_for_runtime(runtime)` — filtered by runtime.
- `execution_registers_all()` — every entry (for celery / docs).

`_DOMAINS` shrinks to `[]` when the repo split lands (see
`NEXT_BEST_STEPS.md` §7q Phase 3); until then it lists the
platform's own domains so dev / cold-boot keeps working.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_platform.jobs.domain import ControlRegister, ExecutionRegister

if TYPE_CHECKING:
    from ai_platform.jobs.job_definition_service import JobDefinitionService


_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DomainModules:
    control: str       # module exposing register_control
    execution: str     # module exposing register_execution
    runtime: str       # which worker runtime runs this domain's jobs


_DOMAINS: list[_DomainModules] = [
    # The synthetic `_demo` domain ships with the platform purely so
    # `docker compose up` and CI stay green. Math (and any friend's
    # domain) arrives via `aiplatform deploy` → CodePackage catalog
    # → `install_*_packages_for_*` → catalog-driven discovery
    # (`*_registers_from_catalog`). This hardcoded list is the
    # cold-boot fallback only.
    _DomainModules(
        "aiplatform_demo.control",
        "aiplatform_demo.execution",
        "default",
    ),
]


def _control(module_path: str) -> ControlRegister:
    return importlib.import_module(module_path).register_control


def _execution(module_path: str) -> ExecutionRegister:
    return importlib.import_module(module_path).register_execution


def _split_entrypoint(entrypoint: str) -> tuple[str, str]:
    """Split a ``module.path:callable`` string into ``(module_path, attr)``.

    Catalog entrypoints come in as the same shape `aiplatform deploy`
    writes — `mathai.math_qa.control:register_control`. The catalog
    helpers use this to import the callable.
    """
    if ":" not in entrypoint:
        raise ValueError(
            f"Entrypoint {entrypoint!r} must be 'module.path:callable'"
        )
    module_path, attr = entrypoint.split(":", 1)
    return module_path, attr


# ---------------------------------------------------------------------------
# Catalog-driven discovery (the primary path post Phase 1)
# ---------------------------------------------------------------------------


def control_registers_from_catalog(
    jd_service: "JobDefinitionService",
) -> list[ControlRegister]:
    """Read JobDefinition rows + import each unique `control_entrypoint`.

    Dedups: multiple rows can share the same entrypoint (a domain that
    declares several JobControls), and we only want to import each
    module once. Rows with empty `control_entrypoint` (pre-Phase-1
    records) are silently skipped — they'll be overwritten on the
    next auto-deploy.

    Best-effort, mirrors [[control_registers]]: *any* import failure
    → log + skip so a missing or incompatible wheel degrades the API
    into serving only the domains it could resolve (issue #46).

    Returns an empty list if the catalog query itself fails (DB down
    on cold boot) — the caller can then fall back to
    `control_registers()` to keep boot alive.
    """
    try:
        rows = jd_service.list()
    except Exception as exc:  # noqa: BLE001 — best-effort
        _log.warning(
            "control_registers_from_catalog: catalog list failed (%s) — "
            "returning empty so caller can fall back",
            exc,
        )
        return []

    seen: set[str] = set()
    out: list[ControlRegister] = []
    for row in rows:
        ep = (row.control_entrypoint or "").strip()
        if not ep or ep in seen:
            continue
        seen.add(ep)
        try:
            module_path, attr = _split_entrypoint(ep)
            module = importlib.import_module(module_path)
            out.append(getattr(module, attr))
        except Exception as exc:  # noqa: BLE001 — best-effort, isolate one bad domain
            # A malformed/incompatible domain (import raising *anything* —
            # TypeError, RuntimeError, an incompatible-dep break, …) must
            # degrade to "that job type is unavailable", never take down
            # every other domain on this runtime. Log the traceback so the
            # offending domain is diagnosable. See issue #46.
            _log.warning(
                "control_registers_from_catalog: skipping %s — %s",
                ep, exc, exc_info=True,
            )
    return out


def execution_registers_from_catalog(
    jd_service: "JobDefinitionService",
    runtime: str,
) -> list[ExecutionRegister]:
    """Worker-side analog of [[control_registers_from_catalog]].

    Filters JobDefinitions by `runtime_selector`, then imports each
    unique `code_entrypoint`. Empty fallback shape on catalog failure.
    """
    try:
        rows = jd_service.list(runtime_selector=runtime)
    except Exception as exc:  # noqa: BLE001 — best-effort
        _log.warning(
            "execution_registers_from_catalog: catalog list failed (%s) — "
            "returning empty so caller can fall back",
            exc,
        )
        return []

    seen: set[str] = set()
    out: list[ExecutionRegister] = []
    for row in rows:
        ep = (row.code_entrypoint or "").strip()
        if not ep or ep in seen:
            continue
        seen.add(ep)
        try:
            module_path, attr = _split_entrypoint(ep)
            module = importlib.import_module(module_path)
            out.append(getattr(module, attr))
        except Exception as exc:  # noqa: BLE001 — best-effort, isolate one bad domain
            # A malformed/incompatible domain (import raising *anything* —
            # TypeError, RuntimeError, an incompatible-dep break, …) must
            # degrade to "that job type is unavailable", never crash-loop
            # the whole worker runtime. Log the traceback so the offending
            # domain is diagnosable. See issue #46.
            _log.warning(
                "execution_registers_from_catalog: skipping %s — %s",
                ep, exc, exc_info=True,
            )
    return out


# ---------------------------------------------------------------------------
# Hardcoded fallback (cold-boot only)
# ---------------------------------------------------------------------------


def control_registers() -> list[ControlRegister]:
    """Hardcoded `_DOMAINS` fallback for the API (cold-boot only).

    Catalog-driven discovery is the primary path
    ([[control_registers_from_catalog]]). This stays as the
    fall-through when the catalog is empty (fresh box, before any
    deploy) or unreachable. Same ModuleNotFoundError tolerance.
    """
    out: list[ControlRegister] = []
    for d in _DOMAINS:
        try:
            out.append(_control(d.control))
        except ModuleNotFoundError as exc:
            _log.warning(
                "control_registers: skipping %s — not importable (%s). "
                "Was the wheel deployed to the CodePackage catalog?",
                d.control, exc,
            )
    return out


def execution_registers_for_runtime(runtime: str) -> list[ExecutionRegister]:
    """Hardcoded `_DOMAINS` fallback for a worker (cold-boot only).

    Primary path is [[execution_registers_from_catalog]]. Same posture.
    """
    out: list[ExecutionRegister] = []
    for d in _DOMAINS:
        if d.runtime != runtime:
            continue
        try:
            out.append(_execution(d.execution))
        except ModuleNotFoundError as exc:
            _log.warning(
                "execution_registers: skipping %s — not importable (%s). "
                "Was the wheel deployed to the CodePackage catalog?",
                d.execution, exc,
            )
    return out


def execution_registers_all() -> list[ExecutionRegister]:
    """Every domain's execution plane — for celery / the workflow generator.

    Safe in the default runtime: building a JobExecution never imports a
    runtime-specific dep (e.g. crewai) — those imports are lazy inside nodes.
    """
    return [_execution(d.execution) for d in _DOMAINS]
