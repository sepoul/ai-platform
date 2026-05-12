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
from mathapp.composition_root import DOMAINS

_workspace = bootstrap_workspace()
_domains = register_domains(DOMAINS, _workspace)
_compute = bootstrap_compute(_workspace.executor, _domains.job_definitions)

app = build_api(workspace=_workspace, domains=_domains, compute=_compute)
