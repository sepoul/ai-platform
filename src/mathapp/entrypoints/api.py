"""Math AI HTTP entrypoint.

Four helpers do the heavy lifting:
  - `bootstrap_workspace()`  — backend selection (local | b2) + storage wiring.
  - `register_domains(...)`  — walk `DOMAINS`, register jobs, collect routers.
  - `bootstrap_compute(...)` — pick a compute backend (poll | thread | celery).
  - `build_api(...)`         — mount platform + domain routers, return FastAPI.

Adding a domain means appending to `mathapp.composition_root.DOMAINS`.
Switching a backend means setting `BACKEND` (storage) or `COMPUTE`
(worker model). None of these touch this file.
"""
from __future__ import annotations

from ai_platform.api.app import build_api
from ai_platform.compute.bootstrap import bootstrap_compute
from ai_platform.jobs.bootstrap import register_domains
from ai_platform.workspace.bootstrap import bootstrap_workspace
from mathapp.composition_root import all_domains

_workspace = bootstrap_workspace()
# API serves submission/result for every job type, across all runtimes.
_domains = register_domains(all_domains(), _workspace)
# Compute runs the execution plane; hand it JobExecution views. (In poll/
# celery mode the API doesn't run jobs, but thread mode does — so it needs
# the engine views regardless.)
_executions = {name: jd.execution for name, jd in _domains.job_definitions.items()}
_compute = bootstrap_compute(_workspace.executor, _executions)

app = build_api(workspace=_workspace, domains=_domains, compute=_compute)
