"""Assemble a wired-up FastAPI from a workspace + a set of registered
domains.

Owns three things the composition root used to do inline:
  - Initialize the platform DI singletons (`init_platform`).
  - Mount the four platform routers (jobs / job_runs / workflows /
    prompts) — the discriminated-union response models depend on every
    `JobControl` already being registered, which `register_control_domains`
    guarantees.
  - Mount each domain's routers + a small health endpoint.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_platform.api.routers import prompts as platform_prompts
from ai_platform.api.routers import workflows as platform_workflows
from ai_platform.api.routers.artifacts import make_artifacts_router
from ai_platform.api.routers.job_logs import router as platform_job_logs
from ai_platform.api.routers.job_runs import make_job_runs_router
from ai_platform.api.routers.jobs import make_jobs_router
from ai_platform.compute.base import ComputeBackend
from ai_platform.jobs.bootstrap import ControlBootstrap
from ai_platform.runtime.registry import init_platform
from ai_platform.workspace.bootstrap import WorkspaceBootstrap


def build_api(
    *,
    workspace: WorkspaceBootstrap,
    domains: ControlBootstrap,
    compute: ComputeBackend,
    title: str = "Math AI API",
) -> FastAPI:
    init_platform(
        workspace.platform_client,
        workspace.executor,
        compute,
        workspace.artifact_service,
    )

    app = FastAPI(title=title)

    # CORS — opt-in via env. Empty default keeps prod posture closed; set
    # `CORS_ALLOW_ORIGINS=http://localhost:3000` (comma-separated) for the
    # host-side Next.js dev server.
    raw_origins = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if raw_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[o.strip() for o in raw_origins.split(",") if o.strip()],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Routers see only the control plane — no engine objects in the API.
    app.include_router(make_jobs_router(domains.job_controls), tags=["Platform / Jobs"])
    app.include_router(make_job_runs_router(domains.job_controls), tags=["Platform / Jobs"])
    app.include_router(platform_workflows.router, tags=["Platform / Workflows"])
    app.include_router(platform_prompts.router, tags=["Platform / Prompts"])
    app.include_router(
        make_artifacts_router(domains.artifact_types, domains.artifact_owners)
    )
    app.include_router(platform_job_logs, tags=["Platform / Jobs"])

    for router in domains.routers:
        app.include_router(router)

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    return app
