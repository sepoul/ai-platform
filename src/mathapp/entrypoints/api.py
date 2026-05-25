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

Adding a domain means appending to `mathapp.composition_root._DOMAINS`.
"""
from __future__ import annotations

from ai_platform.api.app import build_api
from ai_platform.compute.bootstrap import bootstrap_compute
from ai_platform.jobs.bootstrap import register_control_domains
from ai_platform.workspace.bootstrap import bootstrap_workspace
from mathapp.composition_root import control_registers

_workspace = bootstrap_workspace()
# Control plane only — every job type, across all runtimes, no engine import.
_domains = register_control_domains(control_registers(), _workspace)
_compute = bootstrap_compute(_workspace.executor, {})

app = build_api(workspace=_workspace, domains=_domains, compute=_compute)
