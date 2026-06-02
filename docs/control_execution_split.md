# Control plane / execution plane split

_Status: **complete** — Phases 0–1 landed (1c-iv `bcc8a14`). The API imports
no engine; `JobDefinition` is retired. Phase 3 (physical packaging) remains
optional. Last updated 2026-05-25._

> **Naming:** the control-plane type is `JobControl` (not `JobSpec`) — the
> platform already has a `JobSpec` (per-run job identity in
> `job_repository.py`). `JobControl` ↔ `JobExecution` are the two planes.
> (Phase 0 shipped it as `JobSpec`; the split commit renames it.)

## The problem

A job has two audiences with disjoint needs:

- **Control plane** — the API process. Accepts submissions, renders the
  workflow graph, returns typed results. Needs *schemas* only.
- **Execution plane** — a worker. Runs the pydantic_graph (or crew) to
  completion. Needs the graph, nodes, deps factory, persistence hooks.

Today a single god-object, `JobDefinition`
([`execution_policy.py`](../src/ai_platform/jobs/execution_policy.py)),
fuses both. To *register* a job the API has to *build* a `JobDefinition`,
which constructs the graph — so the API process imports execution code
(`pydantic_graph`, and lazily `crewai`). That coupling is what forces the
"load-bearing rule" (heavy imports kept lazy) and is the deeper reason a
worker runtime's dependency conflicts (CrewAI ⇄ Logfire) leak toward the
API at all.

**The prize:** once the API imports only control-plane code, it can never
pull a runtime's deps, the load-bearing rule disappears, and runtime
isolation (see [`runtimes.py`](../src/ai_platform/jobs/runtimes.py)) falls
out as a special case instead of being bolted on. This split *subsumes*
the `api-runtime-decoupling` TODO.

## The two planes

| `JobDefinition` field | Plane | Why |
|---|---|---|
| `name` | both | join key |
| `graph_ref` → `label` | control | human label |
| `submit_input_type` | control | submit request schema (discriminated union) |
| `result_type` | control | typed result schema (discriminated union) |
| `edges` | control | topology rendering |
| `policy.gates[].review_type` | control | review request schema |
| `fetch_result` | control | workspace read for the result endpoint |
| `graph` | execution | the engine |
| `start_node_key`, `node_registry` | execution | the nodes |
| `deps_factory` | execution | builds run deps |
| `extract_result` | execution | state → typed result |
| `persistence` | execution | artifact persistence hooks |
| `state_type` | execution | graph state model |
| `policy` (executable) | execution | gate checks during the run |

`NodeGate` (`node_name` + `review_type`) is a light, control-safe type
referenced by both planes: the API uses it for the review schema, the
worker for gate checks + the resume merge.

The two views are realized as `JobSpec` and `JobExecution` in
[`execution_policy.py`](../src/ai_platform/jobs/execution_policy.py).

## The two leaks (Phase 2 work)

Reading every router, the API consumes only the control subset — with
exactly two leaks into execution:

1. **Topology read off the graph at request time.**
   [`workflows.py`](../src/ai_platform/api/routers/workflows.py) reads
   `node_registry` (the engine) to render stages. **Fix (agreed): the
   worker generates a JSON workflow descriptor; the API just serves it.**
   The API introspecting `pydantic_graph` per request was premature
   coupling — the topology is static per-deploy. A **manual admin
   command** runs in an engine context (default runtime; building a
   JobDefinition doesn't import `crewai` per the load-bearing rule),
   introspects each graph + policy + edges + submit schema, and writes a
   runtime-agnostic JSON descriptor (exactly today's `WorkflowSpecResponse`
   shape) to the backend-agnostic **blob store** (`PlatformClient.file_repo`,
   key `workflows/<job_type>.json`). The API reads + serves it; **optional**
   — absent ⇒ empty/404. No engine import.

2. **Review-merge runs in the API. ✅ DONE (`d30c40b`).**
   The review endpoint used to rebuild `state_type` and call
   `state.set_review(...)`. Now the API validates the body against the
   gate schema and parks the raw payload on `JobState.pending_review`
   (→ `PENDING`); the **worker** merges it into state on resume
   ([`job_runner.py`](../src/ai_platform/jobs/job_runner.py)) and clears
   it. (Chosen over a review *artifact* + id indirection: a review is
   small, ephemeral execution input, not a durable output.)

## Packaging strategy

There is no packaging substrate today —
[`pyproject.toml`](../pyproject.toml) is just pytest config, one flat
`src/` tree copied into every image. Two routes:

- **Logical split (now):** split `JobDefinition` into `JobSpec` +
  `JobExecution`, separate each domain into control/execution *modules*,
  enforce "control never imports execution." The API imports only control
  modules. ~90% of the benefit, reversible.
- **Physical split (later, optional):** real installable packages
  (`platform-core`, `platform-api`, `platform-worker-*`,
  `domain-*-control`, `domain-*-exec`) with per-image deps. Only if import
  discipline proves insufficient.

We do the logical split first.

## Phases

Phase 1 is landed as green increments (the leak fixes come first, while
`JobDefinition` still exists, so the final split is trivial):

- **Phase 0 — seam (done, `fb96cc4`).** `JobControl`/`JobExecution` as
  views over `JobDefinition`. Zero behavior change; boundary tested.
- **Phase 1a — review-as-data (done, `d30c40b`).** Leak #2 fixed; API no
  longer touches the state model.
- **Phase 1b — workflow descriptor (done).** `mathapp.entrypoints.gen_workflows`
  introspects each graph and parks `{job_type: descriptor}` as `workflows.json`
  in the blob store; the workflows router serves it (optional — empty until
  generated). Leak #1 fixed; the API no longer imports `pydantic_graph`.
  **Deploy step:** run `python -m mathapp.entrypoints.gen_workflows` (engine
  context) after deploy / graph changes.
- **Phase 1c — invert ownership.** Done as green sub-steps using the
  `.control` / `.execution` views as a bridge (each side migrates while
  domains still build `JobDefinition`; the god-object is retired last):
  - **1c-i (done).** `JobSpec`→`JobControl`; `edges`→execution plane.
  - **1c-ii (done, `a742893`).** Execution side → `JobExecution`:
    worker/compute/job_runner take `JobExecution` (entrypoints pass
    `jd.execution` views).
  - **1c-iii (done, `6959f58`).** Control side → `JobControl`: registry
    stores `jd.control`; routers consume `JobControl`; `get_job_controls`.
    (API still *imports* the engine at bootstrap — domains build
    `JobDefinition`; removed in 1c-iv.)
  - **1c-iv (done, `bcc8a14`).** Domains build `JobControl` + `JobExecution`
    directly in `control.py` / `execution.py` (`register_control` /
    `register_execution`); composition_root loads control (all domains) for
    the API, execution-per-runtime for workers; `build_workflow_descriptor`
    takes `(control, execution)`. `JobDefinition` + the views are gone.
    `GraphCheckpoint` extracted to `ai_platform.jobs.checkpoint` (pure
    pydantic) — it was the last engine leak (`result_fetcher` →
    `fetch_result` → API pulled it from `graph_execution`). **Verified: the
    API imports neither `pydantic_graph` nor `crewai`.** The load-bearing
    rule is narrowed, not deleted — it now guards the two all-execution
    consumers (the descriptor generator + single-pool celery), not the API.
- **Phase 3 — platform-enforced boundary (done).** Instead of trusting
  `control.py` to stay engine-free, the platform *blocks* the engine. A
  `sys.meta_path` guard ([`import_guard.py`](../src/ai_platform/jobs/import_guard.py))
  raises `ControlPlaneViolation` if a denied module (`pydantic_graph`,
  `crewai`) is imported; the API entrypoint arms it before importing any
  domain, so a stray engine import crashes the API at startup with the
  offender named. Blunt and unbypassable. It immediately caught two real
  leaks: `compute.base → graph_execution` and `bootstrap_compute → poll →
  worker_loop → job_runner` both pulled `pydantic_graph` into the API.
  Fixes: `graph_execution` imports the engine only under `TYPE_CHECKING`
  (the annotations are stringized); the poll/thread backends lazy-import the
  worker loop inside `start_worker`/`_tick`, so the `enqueue` path the API
  uses is engine-free. Verified by `tests/test_import_guard.py` (incl. a
  subprocess that boots the real API entrypoint under the guard).
- **Phase 3b — physical packaging (DONE).** True source split into three
  installable packages under `packages/{core,api,worker}`, import paths
  unchanged via PEP-420 namespace packages. Per-service Dockerfiles install
  ONE package from core + itself (path source) → the api image has no engine
  or worker source; the worker image has no api source. Verified: a standalone
  `uv pip install -e packages/api` imports the control plane with
  pydantic_graph/pydantic_ai/crewai/logfire all absent. Notes below describe
  the plan as executed.

  **Workspace layout**
  ```
  pyproject.toml                      # [tool.uv.workspace] members=["packages/*"] + pytest
  packages/core/pyproject.toml        # name mathapp-core; shared deps only
  packages/core/src/...
  packages/api/pyproject.toml         # deps: mathapp-core + fastapi + uvicorn
  packages/api/src/...
  packages/worker/pyproject.toml      # deps: mathapp-core + pydantic_graph + pydantic_ai
  packages/worker/src/...             #   + optional-deps: crewai (the crewai runtime)
  ```

  **Module partition** (as deployed — the api/worker split is along
  *platform layers*, not domain layers; all domain code lives in core):
  - **core** — all shared platform + ALL domain code:
    - platform: `ai_platform/{workspace,compute,runtime,utilities,
      ai/prompts}`, `ai_platform/jobs/*` EXCEPT `job_runner.py` +
      `worker_loop.py` (which need the engine at module load),
      `mathapp/composition_root.py`, `scripts/`.
    - domain: `mathai/<d>/{models,artifacts,state,registry,crew/callbacks,
      tools,gates,control,workflow,execution}` (+ `crew/{personae,
      crew_builder}` for `math_conversation`), `mathai/workspace`.
    - deps: pydantic, storage (b2sdk, psycopg), celery[redis], httpx,
      pyyaml, figure/doc libs. No FastAPI, no engine.
  - **api (control)** — `ai_platform/api/{app,routers,schemas}` +
    `mathapp/entrypoints/api.py`. **No domain code** (it's all in core).
    deps: core + fastapi + uvicorn + python-multipart.
  - **worker (execution)** — `ai_platform/jobs/{job_runner,worker_loop}`,
    `ai_platform/ai/{providers,run_context}`, `mathapp/entrypoints/{worker,
    celery_app,gen_workflows,crewai_smoke}`. **No domain code** — every
    domain ships in its own package now (`packages/math-qa/`,
    `packages/math-conversation/`). The worker's `[default]` extra
    installs `mathai-math-qa[execution]`, which transitively pulls
    pydantic-ai-slim[anthropic,duckduckgo,logfire]; `[crewai]` installs
    `mathai-math-conversation[execution]`, which transitively pulls
    crewai[anthropic]. Worker base ships only `pydantic-graph` (needed
    by both runtimes). The two extras stay mutually exclusive over the
    otel-sdk pin — each runs as its own image.

  Isolation between runtimes is enforced by three mechanisms, NOT by where
  source files live:
  1. **Per-image deps** — the api image installs no engine; the default
     image has no crewai; the crewai image has no Logfire SDK.
  2. **`composition_root._DOMAINS` manifest** — `execution_registers_for_runtime`
     only imports the execution module for domains assigned to that runtime,
     so the wrong domain's `.py` files (present on disk in core) never load.
  3. **Runtime import guard** (`import_guard.py`) — arms in the api process
     to crash on any `pydantic_graph`/`crewai` import.

  Domain code being shared in core is packaging convenience; the three
  enforcers above are what guarantee a domain can never run on the wrong
  runtime.

  **Namespace packages** (delete `__init__.py` at these split roots; keep on
  leaves): `ai_platform`, `ai_platform.jobs`, `ai_platform.ai`, `mathai`,
  `mathai.<domain>`, `mathapp`, `mathapp.entrypoints`.

  **Pre-step:** verify `mathai/<d>/tools.py` and `mathai/<d>/crew/*` import
  footprint — if they pull `pydantic_ai`/`crewai`, they belong in worker, not core.

  **Tests:** `[tool.pytest.ini_options] pythonpath` = the three `packages/*/src`
  roots (or `uv sync` editable). Target: 100 still green.

  **Docker:** `Dockerfile.api` → `uv pip install packages/api`;
  `Dockerfile.worker` → `uv pip install packages/worker` (`[crewai]` for that pool).
  Result: the api image has no `pydantic_graph` (engine import = ModuleNotFound),
  the crewai worker image has no `logfire` — physical isolation + the import guard.

## Shared library

Already shared and swap-in/out, unaffected by the split: storage backends
(`workspace/storage/*`), compute backends (`compute/*`), the workspace
client, `ArtifactService`, and the `init_platform` registry. These are the
natural contents of a shared core package if/when Phase 3 happens.
