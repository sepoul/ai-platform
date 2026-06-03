# Architecture

Central, "how the platform actually works today" overview. Read this
first if you're trying to understand the codebase as it stands at HEAD;
the operational guides in this directory then go deeper on individual
seams (jobs, prompts, compute, storage, etc).

For the *conceptual contract* (the planes, the ownership model, the
why), see [`platform_design.md`](platform_design.md). This doc is the
*implementation snapshot* — what's wired up, where it lives, how a
request flows through it.

---

## 1. What is this?

`ai-platform` is a Python platform for running domain AI workflows
("jobs"). The split that makes it a *platform* and not a monolith:

- **Core platform** (`packages/core`, `packages/api`, `packages/worker`)
  knows nothing about math. It ships generic catalogs (JobDefinitions,
  ArtifactTypes, CodePackages), a job lifecycle (submit → run →
  result), and a runtime substrate.
- **Domain packages** (`packages/math-qa`, `packages/math-conversation`)
  declare their JobControls + artifact classes via a `register_control`
  entrypoint. They're the *tenant* of the platform.
- **Friend test**: a third party can ship their domain as a wheel +
  `bundle.toml` and run `aiplatform deploy` against a running platform
  instance. The platform installs the wheel on its worker(s) on boot
  and starts serving the friend's jobs. No platform code changes,
  no image rebuild.

---

## 2. System map

```mermaid
graph TB
    subgraph friend["Friend's repo (or this repo's math-qa)"]
        Bundle[bundle.toml + wheel]
        DeployCLI["aiplatform deploy"]
        Bundle --> DeployCLI
    end

    subgraph caller["Runtime caller (notebook / script / domain code)"]
        Session[PlatformSession]
    end

    subgraph platform["ai-platform instance"]
        API[FastAPI API process]

        subgraph catalogs["Three catalogs (Postgres / B2 / local)"]
            JD["job_definitions"]
            AT["artifact_types"]
            CP["code_packages"]
        end

        Files[(File repo<br/>wheel blobs +<br/>artifact blobs)]

        subgraph workers["Worker pools — one per runtime"]
            WD["worker (runtime=default)"]
            WC["worker (runtime=crewai)"]
        end

        API <--> JD
        API <--> AT
        API <--> CP
        API <--> Files

        WD -.boot read.-> CP
        WD -.boot read.-> Files
        WC -.boot read.-> CP
        WC -.boot read.-> Files

        WD -.poll.-> JD
        WC -.poll.-> JD
    end

    DeployCLI -- "POST /code-packages\nPOST /job-definitions\nPOST /artifact-types" --> API
    Session -- "POST /jobs/runs/submit\nGET /jobs/{id}\nGET /jobs/{id}/result" --> API
```

**Plane split** ([`platform_design.md`](platform_design.md) §2 has the
contract; this is the realization):

- **Control plane** = API process + the three catalogs. Knows
  *what* jobs exist and what shape their I/O has. Never executes
  user code.
- **Execution plane** = worker pools. Pulls work, runs the graph,
  writes artifact bytes to storage, reports state back to the
  control plane.
- **Storage plane** = file repo + structured repos. Bytes (wheels,
  artifacts) live here; the control plane only ever holds metadata
  + pointers.

---

## 3. The three catalogs

Every persisted piece of the platform's "what's deployed" state lives
in one of three catalogs. All three share a shape: keyed
`(name, version)` via `id = "{name}@{version}"`, idempotent upsert,
typed record + JSON Schema for its payload.

| Catalog | What it records | Written by | Read by |
|---|---|---|---|
| `job_definitions` | A runnable: schemas (input + result), gates, runtime selector, code entrypoint string | Boot auto-deploy (control.py); `POST /job-definitions` (CLI / friend) | API serves it; future routing cutover (today routing uses the in-memory `_job_controls` dict) |
| `artifact_types` | A `BaseArtifact` subclass: discriminator name + JSON Schema + owning domain | Boot auto-deploy; `POST /artifact-types` | API for catalog browse; future SDK / wheel-driven hydration |
| `code_packages` | An installable wheel: name + version + runtime + blob_id + sha256 + size | `POST /code-packages` (CLI / friend; multipart upload) | Worker on boot — downloads + sha256-verifies + `pip install`s |

Key files:

- [`packages/core/src/ai_platform/workspace/storage/structured/job_definition_repository.py`](../packages/core/src/ai_platform/workspace/storage/structured/job_definition_repository.py)
- [`packages/core/src/ai_platform/workspace/storage/structured/artifact_type_repository.py`](../packages/core/src/ai_platform/workspace/storage/structured/artifact_type_repository.py)
- [`packages/core/src/ai_platform/workspace/storage/structured/code_package_repository.py`](../packages/core/src/ai_platform/workspace/storage/structured/code_package_repository.py)

Service layer (validation + orchestration over the repo):

- `jobs/job_definition_service.py` — validates `runtime_selector ∈ {default, crewai}` and id-vs-name@version consistency.
- `jobs/artifact_type_service.py` — validates non-empty name + domain.
- `jobs/code_package_service.py` — owns the dual write (blob bytes via `FileRepository` + row via the catalog); sha256-verifies on download.

Backends ([`packages/core/src/ai_platform/workspace/storage/backends.py`](../packages/core/src/ai_platform/workspace/storage/backends.py))
plug all three into a `BACKEND` switch: `local` (filesystem JSON),
`b2` (Backblaze), `supabase` (Postgres + Supabase Storage).

---

## 4. Lifecycle: deploy → install → run

### 4.1 Bundle deploy

A friend runs `aiplatform deploy --bundle bundle.toml --api-url http://platform:8000`
(or invokes `ai_platform.bundle.deploy_bundle` programmatically).

```mermaid
sequenceDiagram
    participant CLI as aiplatform deploy
    participant API
    participant FR as FileRepository
    participant CPC as code_packages
    participant JDC as job_definitions
    participant ATC as artifact_types

    CLI->>CLI: Read bundle.toml<br/>(package name/version/runtime/wheel,<br/>control entrypoint, exec entrypoint)
    CLI->>+API: POST /code-packages (multipart wheel)
    API->>FR: put_canonical_file(blob_id, wheel_bytes)
    API->>CPC: upsert(name, version, runtime, blob_id, sha256)
    API-->>-CLI: 201 CodePackageRecord

    CLI->>CLI: import control_entrypoint<br/>→ ControlDomain
    loop For each JobControl in domain
        CLI->>+API: POST /job-definitions
        API->>JDC: upsert
        API-->>-CLI: 201 JobDefinitionRecord
    end

    loop For each BaseArtifact subclass
        CLI->>+API: POST /artifact-types
        API->>ATC: upsert
        API-->>-CLI: 201 ArtifactTypeRecord
    end
```

Order matters: **CodePackage first** — bytes must land before any
worker reads the catalog row that points at them. JobDefinitions +
ArtifactTypes are independently idempotent; partial failure is "re-run
the command".

[`packages/core/src/ai_platform/bundle/__init__.py`](../packages/core/src/ai_platform/bundle/__init__.py)
holds the orchestration; [`packages/core/src/ai_platform/bundle/cli.py`](../packages/core/src/ai_platform/bundle/cli.py)
is the argparse + pretty-print wrapper.

### 4.2 Worker boot

When a worker starts (entrypoint at [`packages/worker/src/ai_platform/entrypoints/worker.py`](../packages/worker/src/ai_platform/entrypoints/worker.py)),
it pulls every CodePackage row for its runtime and pip-installs the
ones it doesn't already have:

```mermaid
sequenceDiagram
    participant W as Worker process
    participant CPC as code_packages
    participant FR as FileRepository
    participant Pip as pip subprocess

    W->>W: bootstrap_workspace()<br/>(reads BACKEND env, opens connections)
    W->>+CPC: list(runtime_selector="default")
    CPC-->>-W: [CodePackageRecord, ...]
    loop For each record
        W->>W: importlib.metadata.version(name)
        alt version matches catalog
            W->>W: log "already installed — skipping"
        else not installed / version mismatch
            W->>+FR: get_canonical_file_bytes(blob_id)
            FR-->>-W: wheel_bytes
            W->>W: verify sha256
            W->>+Pip: pip install --force-reinstall <wheel>
            Pip-->>-W: rc=0
            W->>W: log "Installed CodePackage <id>"
        end
    end
    W->>W: register_execution_domains(...)<br/>(resolves entrypoints — now importable)
    W->>W: compute.start_worker(...)  -- enter run loop
```

Best-effort: a single install failure logs + continues; a failed
`list()` (DB down) skips the install pass entirely. The worker still
serves the JobDefinitions whose code is baked into its image. See
[`packages/core/src/ai_platform/jobs/code_package_install.py`](../packages/core/src/ai_platform/jobs/code_package_install.py).

### 4.3 Job submission

A runtime caller uses `PlatformSession` (or hits the API directly):

```mermaid
sequenceDiagram
    participant Caller as PlatformSession
    participant API
    participant Q as Compute queue
    participant W as Worker (right runtime)
    participant JR as job_repository
    participant FR as FileRepository

    Caller->>+API: POST /jobs/runs/submit<br/>{job_type, ...params}
    API->>JR: insert JobRecord (PENDING)
    API->>Q: enqueue(job_id)
    API-->>-Caller: 201 {job_id, status: PENDING}

    Caller->>Caller: handle.wait(timeout=60)
    loop poll every poll_interval
        Caller->>API: GET /jobs/{id}
        API->>JR: get
        API-->>Caller: status row
    end

    Q->>W: dispatch (poll or broker)
    W->>JR: mark RUNNING
    W->>W: run job graph (writes artifact bytes)
    W->>FR: put artifact payloads
    W->>JR: write artifact refs + mark SUCCEEDED

    Caller->>+API: GET /jobs/{id}/result
    API->>JR: get
    API->>FR: hydrate artifact refs
    API-->>-Caller: 200 {result: ...}
```

`PlatformSession` ([`packages/core/src/ai_platform/session/session.py`](../packages/core/src/ai_platform/session/session.py))
is just a typed httpx wrapper over the API; it owns the connection,
exposes the three catalog reads, and gives `JobHandle.wait()` /
`.result()` for lifecycle.

---

## 5. Runtime separation

Two worker pools exist for one reason: **otel-sdk pin conflict** —
Logfire (used by `pydantic_ai` for tracing) needs
`opentelemetry-sdk >= 1.39`; CrewAI pins `< 1.35`. They can't share
an interpreter.

In prod, both pools run **the same virgin `aiplatform-worker` image**.
The only difference is `WORKER_RUNTIME` env + which wheels the catalog
serves to each pool:

```mermaid
graph LR
    Image[("aiplatform-worker (virgin)<br/>NO domain code<br/>NO LLM stack")]

    subgraph d["worker (WORKER_RUNTIME=default)"]
        Drun["boot: pip install mathai-math-qa[execution]<br/>→ pydantic-ai-slim + Logfire arrive<br/>→ serves math_qa jobs"]
    end

    subgraph c["worker-crewai (WORKER_RUNTIME=crewai)"]
        Crun["boot: pip install mathai-math-conversation[execution]<br/>→ crewai[anthropic] arrives<br/>→ serves math_conversation jobs"]
    end

    Image -.same image.-> Drun
    Image -.same image.-> Crun
    Cat[(code_packages)] -.runtime_selector=default.-> Drun
    Cat -.runtime_selector=crewai.-> Crun
```

Each worker reads `WORKER_RUNTIME` env, queries the catalog for that
runtime, installs the wheels, then registers only that runtime's
domains. The otel-sdk pin conflict (Logfire `>=1.39` vs CrewAI
`<1.35`) lives at the **wheel-extras level** now, not the image level
— each runtime's wheels pull a different LLM stack, but the image
they install into is identical.

A friend's domain joins one of the two existing runtimes by declaring
`package.runtime = "default" | "crewai"` in its `bundle.toml`, and
must put its runtime-side deps under an `[execution]` extra (the
platform install pass appends `[execution]` to the install target).
Adding a third runtime means extending `KNOWN_RUNTIMES` in
[`packages/core/src/ai_platform/jobs/job_definition_service.py`](../packages/core/src/ai_platform/jobs/job_definition_service.py)
— no new image required.

---

## 6. Platform and domain are separate, on the worker

In prod, **the worker image carries zero domain code**. Both
`worker` and `worker-crewai` run the identical virgin
`aiplatform-worker` image — only `WORKER_RUNTIME` env differs. The
platform's own domains (math-qa, math-conversation) arrive at boot
via the CodePackage catalog, **the same way a friend's domain does**.

The path math-qa takes is the path your domain takes:

```mermaid
graph LR
    Build[uv build --wheel] --> Deploy[aiplatform deploy<br/>--bundle bundle.toml]
    Deploy --> Cat[(code_packages<br/>job_definitions<br/>artifact_types)]
    Cat --> Worker[worker boot:<br/>install_packages_for_runtime]
    Worker --> Reg[register_execution_domains]
    Reg --> Serve[serve jobs]
```

This means the prod posture matches the friend-test posture:

- No `Dockerfile.<your-domain>` for prod images. The CI build matrix
  produces *only* `aiplatform-worker` (virgin), `aiplatform-api`,
  `math-ui`, `platform-ui` — none of which know about any specific
  domain.
- Adding or removing a domain is a `aiplatform deploy` away. No image
  rebuild, no compose change, no platform PR.
- The local-dev path (`docker compose up`) still bakes math-qa and
  math-conversation via `Dockerfile.worker-domain` as a convenience
  (skips the deploy step on a fresh box with an empty catalog). The
  prod compose **does not** use that Dockerfile.

The same shift is *not yet* applied to the API: `Dockerfile.api`
still pre-installs the math-qa and math-conversation *control*
modules so the API's boot-time `register_control_domains` can import
them. Closing that gap (an API-side analog of the worker's catalog
install pass) is on-deck — see §8.

---

## 7. Key files

The pieces a new reader needs to find, mapped to where they live.

| Topic | Where |
|---|---|
| Bundle deploy CLI + orchestration | `packages/core/src/ai_platform/bundle/{cli,manifest,__init__}.py` |
| PlatformSession + JobHandle | `packages/core/src/ai_platform/session/session.py` |
| Three catalogs (records) | `packages/core/src/ai_platform/workspace/storage/structured/{job_definition,artifact_type,code_package}_repository.py` |
| Three catalogs (Supabase impl) | `packages/core/src/ai_platform/workspace/storage/structured/supabase.py` |
| Three services | `packages/core/src/ai_platform/jobs/{job_definition,artifact_type,code_package}_service.py` |
| Worker boot install | `packages/core/src/ai_platform/jobs/code_package_install.py` |
| Worker entrypoint | `packages/worker/src/ai_platform/entrypoints/worker.py` |
| API app + router wiring | `packages/api/src/ai_platform/api/app.py` |
| API routers | `packages/api/src/ai_platform/api/routers/{jobs,job_runs,job_definitions,artifact_types,code_packages,...}.py` |
| Runtime DI singletons | `packages/core/src/ai_platform/runtime/registry.py` |
| Backend factory | `packages/core/src/ai_platform/workspace/storage/backends.py` |
| Postgres schema | `supabase/migrations/000{1,3,4,5}*.sql` |
| Composition root (which domain runs on which runtime) | `packages/core/src/ai_platform/composition_root.py` |

---

## 8. Loose ends + on-deck

What's deliberately not coupled yet, so the next person extending the
platform doesn't trip:

- **API image is not yet virgin.** `Dockerfile.api` pre-installs the
  math-qa and math-conversation *control* modules so the boot-time
  `register_control_domains` can import them. The analog of the
  worker's `install_packages_for_runtime` doesn't exist for the API
  yet — adding it (or making the auto-deploy optional and requiring
  explicit `aiplatform deploy` for all domains, friend and platform
  alike) is the next axis of the platform/domain split cleanup.
- **JobDefinition ↔ CodePackage.** A JobDefinition row carries
  `code_entrypoint` as a free string. There's no foreign key into
  `code_packages` and the worker doesn't verify the entrypoint
  resolves to *this* deployed package. Tightening this (an optional
  `code_package_ref`) is a substrate-level cleanup if/when it bites.
- **Catalog-driven routing cutover.** The API still resolves
  JobControls via the in-memory `_job_controls` dict populated at
  boot. The catalog row is recorded as a parallel artifact — when a
  friend POSTs a new JobDefinition, the API knows about the row but
  won't route to it until the next API restart. Live routing from
  the catalog is a future PR; pairs with the API-virgin item above.
- **`[execution]` extra convention.** The worker install pass appends
  `[execution]` to every wheel target. A friend's wheel that uses a
  different extra name installs the base package but skips its
  runtime stack (pip just warns). Documented in
  `packages/{math-qa,math-conversation}/bundle.toml`.
- **Wheel deps.** `pip install` runs with default dep resolution.
  Friends deploying to *their* platform decide their own dep set;
  there's no constraints/sandbox/signature check today.
- **Single Celery pool.** [`celery_app.py`](../packages/worker/src/ai_platform/entrypoints/celery_app.py)
  registers all runtimes in one pool — fine in dev, won't survive
  the otel pin conflict if Logfire + CrewAI ever load in the same
  process. Not wired into the CodePackage install path. The
  poll-based `worker.py` is the prod path.
- **Bundle versioning.** `bundle.toml`'s `package.version` becomes
  the version for *all three* records the bundle creates. A future
  manifest extension can decouple wheel version from job/artifact
  versions; nobody's needed it.

---

## See also

- [`platform_design.md`](platform_design.md) — the conceptual contract (planes, ownership, vocabulary).
- [`jobs_spec.md`](jobs_spec.md) — job lifecycle deep-dive (states, checkpoints, gates).
- [`control_execution_split.md`](control_execution_split.md) — why control and execution are split, and the import rules that keep them split.
- [`compute_backends.md`](compute_backends.md) — pluggable compute (poll / thread / celery).
- [`storage_backends.md`](storage_backends.md) — pluggable storage (local / B2 / Supabase).
- [`onboarding_new_job_type.md`](onboarding_new_job_type.md) — the cookbook for adding a domain workflow.
- [`deployment_hetzner.md`](deployment_hetzner.md) — the prod box, images, redeploy script.
