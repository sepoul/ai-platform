# AI Platform — Design Contract

> The platform's vocabulary, ownership model, and lifecycle. Conceptual
> only — implementation details belong in the companion specs (Control
> Plane API, Bundle Manifest, Runtime Catalog).

---

## 1. One-sentence definition

> Tenants use platform-defined AI workflows to produce typed artifacts on
> their own compute and storage, with provenance, telemetry, and
> reusability built in.

The platform's job is **the catalog and the orchestration**.
The tenant's job is **the compute and the data**.

---

## 2. The three planes

The platform is split into three planes with clean ownership boundaries.

| Plane | Owned by | Holds |
|---|---|---|
| **Control plane** | Platform | Catalogs, definitions, runtime registry, configuration, lineage, run metadata, telemetry routing |
| **Execution plane** | Tenant | Compute that pulls work and runs job code |
| **Storage plane** | Tenant | Artifact payload bytes, large blobs, secrets |

**Boundary rules — these are the load-bearing invariants.**

- The control plane never holds artifact payload bytes. It holds **metadata**
  (id, type, version, refs, lineage edges) and a **storage_ref** that points
  into the tenant's storage plane.
- The execution plane reads job definitions from the control plane, runs the
  code, writes artifact bytes directly to the storage plane, and reports
  metadata + events back to the control plane. **Payload bytes never
  traverse the control plane.**
- The control plane never executes user code. It hands a runtime +
  entrypoint + input to the execution plane and waits.

These three rules are why the platform can be operated as a hosted service
without ever holding a tenant's data.

The execution plane is **pluggable per room**: each AIRoom selects one
attach protocol (worker-poll, queue-broker, …) that determines how its
compute pulls work. See §8.1.

---

## 3. Vocabulary

The platform contract uses exactly these terms. Every implementation
artifact maps to one.

| Term | Plane | One-line definition |
|---|---|---|
| **AIRoom** | Control | A scoped environment of a tenant (e.g. prod / staging). Hosts many Domains. |
| **Domain** | Control | A bundle of related Job Definitions and the Artifact Types they produce. Scoped inside one AIRoom. |
| **Artifact Type** | Control | A versioned typed-output schema. Catalog entry. |
| **Artifact** | Storage (payload) + Control (metadata) | A persisted instance of an Artifact Type. |
| **Job Definition** | Control | A versioned, runnable thing. Carries runtime selector, code package, entrypoint, input schema, output artifact bindings, execution policy, and an optional Representation. |
| **Job Run** | Control (metadata) + Execution (process) | One execution of a Job Definition. |
| **Runtime** | Control (catalog) + Execution (image) | A platform-authored versioned dependency bundle + execution adapter. |
| **Representation** | Control | An optional structural view of a Job Definition (graph, crew, flat, …). Pluggable, per-runtime. |
| **Bundle** | Control (deployable artifact) | A pinned, versioned, deployable set of Domains, Job Definitions, Artifact Types, Prompts, and code packages. The unit of infra-as-code. |
| **Prompt** | Control | A versioned text definition with execution tracking. Catalog entry. |
| **Lineage Edge** | Control | A typed pointer: Run → consumes(Artifact), Run → produces(Artifact), Artifact → derived_from(Artifact). |
| **Event** | Control (typed stream) | A typed run-time signal: RunSubmitted, RunStarted, StepStarted, ArtifactCreated, etc. |

An **AIRoom** hosts many **Domains**. A Domain encapsulates a set of related
workflows and the artifacts they produce. Roughly: AIRoom = environment;
Domain = bundle of related work within that environment.

> **Open**: confirm "AIRoom" as the final external name vs alternatives
> (Studio, Lab, Atelier). Vocabulary lock-in is cheap to defer one revision.

---

## 4. The catalog

The control plane is a typed, versioned **catalog**. It is the only source
of truth for definitions. Every catalog object:

- has a stable id,
- is versioned (semver or monotonic; TBD),
- is referenced by version from other catalog objects (refs are
  version-pinned, not version-floating),
- belongs to exactly one AIRoom (and through it, one Tenant — see §10).

The catalog contains:

- **AIRoom configurations** — name, default runtime selectors, default
  telemetry routing, storage-plane binding (the credentials/refs the
  execution plane uses to write artifacts).
- **Domain registrations** — `{room → list of domains it hosts}`.
- **Artifact Type catalog** — versioned schemas. A new version is a new
  entry; old versions stay queryable for already-produced artifacts.
- **Job Definition catalog** — see §5.
- **Runtime catalog** — see §6.
- **Prompt catalog** — versioned text + execution history.
- **Lineage graph** — typed edges between runs and artifacts.
- **Bundle history** — each room records the bundle versions it has been on.

The catalog offers exactly one external surface: the **Control Plane API**,
which all clients (CLI, SDK, UI, MCP server, future surfaces) consume. No
client has any other backdoor.

> **Open**: object versioning scheme (semver vs monotonic vs hash); ref
> shape (`name@version` vs `id`).

---

## 5. Job Definitions

A Job Definition is the most important object in the catalog. It is a
**scheduler-shaped record at its core**, optionally enriched with a
structural representation.

### 5.1 Core fields (mandatory)

- `id`, `name`, `version`
- `domain` (which Domain it belongs to)
- `runtime_selector` (name@version from the Runtime catalog)
- `code_package` (a reference to an uploaded artifact: a `.whl` or
  equivalent blob, hash-pinned)
- `entrypoint` (a string addressing a callable inside the code package)
- `input_schema` (schema id from the catalog)
- `output_artifact_type_refs` (named map: `output_name →
  artifact_type@version`)
- `execution_policy` (timeout, retries, human gates, idempotency posture)
- `prompt_refs` (named map of prompt references this job uses)

This shape alone is enough to schedule and run anything. It is deliberately
**flat and scheduler-like**, not a graph. A definition with these fields
and nothing else is a valid, runnable, queryable platform object.

### 5.2 Representations (optional, pluggable)

A flat scheduler record is uninteresting to a UI, a reasoning surface, or a
reviewer. The fix is **Representation**: an optional structural view of the
job's internals, attached to the definition, shaped per the runtime's
natural model.

- A pydantic-graph job carries a **graph representation** — nodes, edges,
  gates.
- A multi-agent job carries a **crew representation** — roles, tools,
  collaboration shape.
- A plain Python job carries no representation (`flat`); it remains a
  black box to introspection surfaces, but still runs.

Representations are **opt-in per runtime**, **not enforced**, and **not
the execution model**. The runtime executes the code; the representation
is a side-car description of what's inside, used only for rendering and
reasoning.

This is the design choice that keeps the platform general-purpose: the
catalog is not a graph engine. Definitions are graphs only when the
runtime naturally describes them as graphs — and any other shape is just
as first-class.

Each Runtime declares which representation kinds it supports. The upload
pipeline can derive a representation from the code, or the bundle author
can supply it explicitly.

> **Open**: representation kinds beyond graph / crew / flat (pipeline,
> agent-loop, script, …). Catalog of kinds vs free-form.

---

## 6. Runtimes

A Runtime is a **platform-authored**, versioned bundle. Tenants do not
author runtimes; the catalog of available runtimes is curated by the
platform.

A Runtime catalog entry carries:

- `name`, `version`
- `base_image` (or equivalent — the deployable artifact the execution
  plane installs)
- `dependency_manifest` (what's pinned inside)
- `execution_adapter` (the contract for `submit` / `cancel` /
  `get_status`)
- `supported_representations` (`{graph, crew, flat, …}` subset)

Tenant compute installs one or more runtime images. Each Job Definition
selects exactly one runtime via `runtime_selector`. A Domain is
implicitly pinned to whatever runtimes its definitions reference.

The platform ships an initial catalog of runtimes covering the common
agent and graph frameworks, plus a plain-Python escape-hatch runtime for
jobs that don't need any framework at all.

> **Open**: whether the plain-Python escape-hatch runtime ships in v0 or
> later.

---

## 7. Artifacts and lineage

An Artifact is split across two planes:

- **Catalog metadata** (control plane): `artifact_id`,
  `artifact_type@version`, `produced_by_run_id`,
  `produced_by_job_definition_id`, `created_at`, `storage_ref`,
  validation state.
- **Payload bytes** (storage plane): keyed by `artifact_id`, written
  directly by the executor.

The control plane builds a **lineage graph** from typed edges emitted by
the executor:

- `Run consumes Artifact` (input refs)
- `Run produces Artifact` (output refs)
- `Artifact derived_from Artifact` (when a domain wants to record explicit
  derivation distinct from the produced/consumed edges)

This makes "show me everything derived from input X" a graph query against
the catalog, not a payload scan.

> **Open**: how deep does lineage go? Per-run only, or per-step? Step-level
> is useful for debugging but inflates catalog volume.

---

## 8. Execution & events

### 8.1 Execution-plane attach protocols

The execution plane is **pluggable**. Each AIRoom configures exactly one
attach protocol; workers on the tenant's compute use that protocol to
discover and pull runs from the control plane. Job Definitions are
protocol-agnostic — moving a room from one protocol to another requires no
changes to definitions or code.

Supported protocols:

- **Worker-poll** — workers periodically poll the Control Plane API for
  pending runs scoped to their AIRoom + Runtime. Simplest deployment:
  workers need only outbound HTTPS to the control plane; no additional
  infrastructure. Suitable for low-to-moderate volume.

- **Queue-broker** — the control plane publishes work orders to a message
  broker (Redis, RabbitMQ, SQS, …) that the tenant operates as part of
  their compute infrastructure; workers consume from the broker. Lower
  submit-to-start latency and higher throughput than polling, at the cost
  of running a broker.

- (Pluggable) — additional protocols (websocket push, batch-scheduler
  integration, …) can be added without changing the catalog or the Job
  Definition shape; each protocol is a separate adapter on both sides.

What is **not** a supported protocol: in-process execution, where the
control plane itself runs job code. It would violate the plane separation
(§2) and has no operational story; it is excluded from the contract by
design.

A Room's configuration declares its attach protocol and any
protocol-specific config (broker URL, poll interval, …). Changing the
protocol is a configuration change against the catalog, not a code
change.

### 8.2 How execution happens

1. A client calls `submit_run(job_def_id@version, input_payload)` on the
   Control Plane API.
2. The control plane records a Run (PENDING) and emits `RunSubmitted`.
3. A worker on the tenant's execution plane — bound to one AIRoom and one
   or more Runtimes — pulls the run.
4. The worker installs/uses the runtime image, loads the code package
   (downloaded from the control plane, hash-verified), and invokes the
   entrypoint with the input payload plus a context object.
5. The job runs on the tenant's machine. It writes artifact bytes
   directly to the storage plane and emits events to the control plane.
6. The control plane records the events, updates the run, builds the
   lineage edges, and fans events out to telemetry sinks.

### 8.3 Events are the platform's runtime contract

Events are typed, not strings. Initial vocabulary (minimum viable set):

- `RunSubmitted`, `RunStarted`, `RunCompleted`, `RunFailed`,
  `RunCancelled`
- `StepStarted`, `StepCompleted` (when the Representation defines steps)
- `ArtifactCreated`
- `HumanReviewRequested`, `HumanReviewSubmitted`
- `WorkerLog` (a freeform string event — the escape hatch for ad-hoc
  logging; sinks can render it as a live log stream)

Sinks are platform-configurable per room: structured-log services, OTel
collectors, a database audit log, the live-logs stream for the UI, etc.

> **Open**: model-call and tool-call events (`ModelCallStarted` /
> `Completed`, `ToolCallStarted` / `Completed`) — v0 must, or later? They
> add real value but require runtime adapters to emit them.

### 8.4 Execution semantics

- **Submit** returns immediately with a `run_id`. The Control Plane API is
  fully async by default.
- **Cancellation** is cooperative: setting `cancel_requested` causes the
  executor's next checkpoint to abort. No hard-kill guarantee.
- **Retries**: a definition's `execution_policy` declares max attempts and
  idempotency posture. The platform retries from the last checkpoint when
  the policy allows.
- **Timeouts**: per-run hard ceiling from `execution_policy`. Per-step is
  a Representation-level concern (only graphs / crews have steps to time).

---

## 9. Bundles — the infra-as-code unit

A Bundle is a pinned, versioned, deployable set of catalog objects plus
their code packages. It is the **only** way real changes reach a room.

A Bundle pins:

- One or more Domains
- All Job Definitions in those Domains
- All Artifact Types referenced
- All Prompts referenced
- The code packages referenced as `.whl` (or equivalent) blobs, hashed
- The Runtime versions referenced (by ref, not embedded)

A Bundle is built locally (`ai-platform bundle build`), pushed to the
control plane (`ai-platform bundle deploy --room prod`), and registered as
the room's current bundle version. Rolling back is "deploy the previous
bundle." Diffs between bundles drive catalog migrations.

Bundles are what make the platform **versioned and reproducible**. A room
at bundle version `2024.11.3` runs exactly the code and definitions that
bundle pinned — every time, on every executor.

> **Open**: bundle manifest format — YAML, Python (Pydantic config), or
> both. A YAML manifest plus typed Python definitions is the working
> recommendation.

---

## 10. Multi-tenancy posture

Single-tenant by default. The contract is shaped so multi-tenant lands
later without breaking changes.

Every catalog object is scoped under an AIRoom. Every AIRoom belongs to a
Tenant. For now, a single implicit `default` Tenant exists; there is no
Tenant table, no auth, no per-tenant isolation beyond room scoping.

Going multi-tenant later means:

- introducing a Tenant table,
- adding `tenant_id` as an indexed column on rooms,
- introducing auth on the Control Plane API,
- adding per-tenant storage-plane bindings and execution-plane attach
  credentials.

No existing catalog object's shape changes. This is the cheap path, and
it is the reason the contract carries AIRoom and Domain even when there
is only ever one of each.

---

## 11. The Control Plane API — single entry, no backdoor

The Control Plane API is the **only** way to interact with the platform
after deploy. CLI, SDK, UI, MCP server, future surfaces are all clients
of it. There is no in-process Python facade for users.

Conceptual surface (endpoints will be specified in the companion API
spec):

- **Rooms** — list, get, configure
- **Domains** — list, get
- **Artifact Types** — list, get, history
- **Artifacts** — list, get (metadata), get_payload (proxies to storage
  plane via signed URL), lineage
- **Job Definitions** — list, get, history
- **Runs** — submit, get, list, cancel, review (human gate), logs (event
  stream), result
- **Runtimes** — list, get (read-only catalog)
- **Prompts** — list, get, history, executions
- **Bundles** — deploy, list, get, rollback
- **Events** — subscribe (server-sent or websocket), query historical

> **Open**: payload retrieval — does the control plane always proxy via
> signed URLs to the storage plane, or does it ever serve bytes directly?
> Working recommendation: signed URLs only. Keeps the "bytes never
> traverse the control plane" rule absolute.

---

## 12. Lifecycle

```
1. Provision        Platform vendor stands up the control plane.
2. Onboard tenant   Tenant signs up; gets an implicit Room.
3. Attach compute   Tenant runs an execution-plane worker with credentials
                    pointing at one (or more) of their rooms.
4. Attach storage   Tenant configures storage-plane credentials on the room.
5. Author bundle    Tenant writes Domains, Job Definitions, Artifact Types,
                    prompts, code, in a repo. Builds a bundle.
6. Deploy bundle    `ai-platform bundle deploy --room prod`. Catalog is
                    updated atomically.
7. Run              Clients submit runs via the Control Plane API. Execution
                    plane pulls and executes. Artifacts land in storage plane.
                    Events stream back.
8. Observe          Lineage and events surface in the UI, MCP, telemetry
                    sinks.
9. Iterate          Author new bundle version. Deploy. Roll back if needed.
```

---

## 13. Out of scope

The platform deliberately does not build the following. They are someone
else's problem unless explicitly reopened.

- Model gateway / LLM routing
- Eval framework / golden-set regression
- Vector store / RAG indexing as a built-in
- Fine-tuning / distillation / training
- Cost accounting and budget enforcement per tenant
- Cross-tenant artifact marketplace
- Built-in human-review UI beyond the gate primitive

---

## 14. Open questions

Numbered for easy reference.

1. **Naming** — AIRoom final, or revisit (Studio, Lab, Atelier).
2. **Versioning scheme** — semver, monotonic, or content-hash for catalog
   objects.
3. **Ref shape** — `name@version` strings vs `(id, version)` tuples in
   cross-references.
4. **Representation catalog** — beyond graph / crew / flat: pipeline,
   agent-loop, script, …?
5. **Plain-Python runtime** — ship in v0 or defer?
6. **Lineage depth** — per-run only, or per-step.
7. **Model/tool-call events** — `ModelCallStarted` etc. in v0 vocabulary
   or later?
8. **Bundle manifest format** — YAML, Python, or both.
9. **Payload retrieval** — signed URLs only, or control-plane proxy ever?
10. **Storage-plane provisioning** — tenant supplies static credentials,
    or control plane issues short-lived ones?
11. **Code package format** — `.whl` only, or also container images and
    tarballs?
12. **Prompt placement** — prompts as their own catalog kind, or as a
    specialization of Artifact Type?
13. **Telemetry routing config** — per-room only, or per-Job Definition
    too?

---

## 15. Deferred decisions

Listed so the absence is not mistaken for a decision.

- Authentication and authorization (deferred with multi-tenancy)
- Secrets management on the tenant side
- A formal SLA / SLO posture for the control plane
- A backup / disaster-recovery story for the catalog
- A formal API stability commitment (v0 / semver / deprecation policy)
- A pricing model
- The MCP server tool vocabulary
- The Patterns / Demos packaging model — likely "a Bundle marked as
  installable demo" but unconfirmed
