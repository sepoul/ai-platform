"""Math AI HTTP entrypoint.

Four helpers do the heavy lifting:
  - `bootstrap_workspace()`        — backend selection (local | b2) + storage.
  - `register_control_domains(...)`— walk domains' control plane, register
    JobControls, collect routers. **Engine-free**: the API never imports the
    graph/crew engine (that lives in each domain's `execution.py`).
  - `bootstrap_compute(...)`       — a ComputeBackend for `enqueue`. The API
    only enqueues; workers execute. So it gets an empty execution map (poll/
    celery `enqueue` ignore it; in-API `thread` execution is not supported
    under the control/execution split — run a worker).
  - `build_api(...)`               — mount platform + domain routers.

Adding a domain means appending to `ai_platform.composition_root._DOMAINS`.
"""
from __future__ import annotations

# Platform-enforced boundary: arm BEFORE importing anything domain-related so
# a stray engine import in a control.py crashes the API at startup, named.
from ai_platform.jobs.import_guard import enforce_control_plane

enforce_control_plane()

import logging  # noqa: E402

from ai_platform.api.app import build_api  # noqa: E402
from ai_platform.compute.bootstrap import bootstrap_compute  # noqa: E402
from ai_platform.jobs.bootstrap import register_control_domains  # noqa: E402
from ai_platform.jobs.code_package_install import install_control_packages_for_api  # noqa: E402
from ai_platform.jobs.runtimes import DEFAULT_RUNTIME  # noqa: E402
from ai_platform.workspace.bootstrap import bootstrap_workspace  # noqa: E402
from ai_platform.composition_root import (  # noqa: E402
    control_registers,
    control_registers_from_catalog,
)

# Surface our own boot-time INFO lines (catalog install, register, etc.).
# Without this, only uvicorn's access log lands on stdout and the
# install/register narrative is invisible in container logs.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_log = logging.getLogger("api.boot")

_workspace = bootstrap_workspace()

# Friend-test path on the API: pull every CodePackage from the catalog
# and pip-install its *control modules only* (no `[execution]` extra)
# before `register_control_domains` tries to import them. This is the
# API-side analog of `install_packages_for_runtime` on the worker.
# Best-effort + idempotent: skips already-installed wheels at matching
# versions, swallows failures so a degraded catalog doesn't dead-end
# API boot.
install_control_packages_for_api(_workspace.code_package_service)

# Discovery: prefer the catalog (JobDefinition.control_entrypoint per
# row, deduped) — this is the seam that lets a friend's domain become
# live without an edit to composition_root. The hardcoded `_DOMAINS`
# fallback covers cold boot (empty catalog) so a fresh deploy still
# brings up the platform's baseline domains.
_registers = control_registers_from_catalog(_workspace.job_definition_service)
if _registers:
    _log.info(
        "control_registers_from_catalog returned %d register(s) — "
        "catalog-driven discovery active",
        len(_registers),
    )
else:
    _log.info(
        "control_registers_from_catalog returned empty — "
        "falling back to hardcoded _DOMAINS for cold boot"
    )
    _registers = control_registers()

# Control plane only — every job type, across all runtimes, no engine import.
_domains = register_control_domains(_registers, _workspace)


def _runtime_for_job_type(job_type: str) -> str:
    """Resolve a job_type's worker runtime for Celery's per-runtime routing
    (issue #66). The JobDefinition catalog's `runtime_selector` is the
    authoritative source and stays current as domains deploy. Unknown or
    unreachable → default runtime (the default consumer then fails fast on
    an unservable job_type). No-op when COMPUTE != celery.
    """
    try:
        return _workspace.job_definition_service.get_by_name(job_type).runtime_selector
    except Exception:
        return DEFAULT_RUNTIME


_compute = bootstrap_compute(
    _workspace.executor, {}, runtime_for_job_type=_runtime_for_job_type
)

app = build_api(workspace=_workspace, domains=_domains, compute=_compute)
