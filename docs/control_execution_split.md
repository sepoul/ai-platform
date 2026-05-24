# Control plane / execution plane split

_Status: Phase 0 (`fb96cc4`) + review-as-data (`d30c40b`) landed. Last updated 2026-05-24._

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
- **Phase 1b — workflow descriptor.** Worker generates JSON; API serves
  it from the blob store. Leak #1 fixed; API stops reading `pydantic_graph`.
- **Phase 1c — invert ownership.** Domains build `JobControl` +
  `JobExecution` directly in separate `control.py` / `execution.py`
  modules. The API registry holds only `JobControl` (imports no engine);
  workers hold `JobExecution` for their runtime. Retire `JobDefinition`.
  composition_root loads control (all domains) for the API,
  execution-per-runtime for workers. Delete the load-bearing rule.
- **Phase 3 — physical packaging (optional).**

## Shared library

Already shared and swap-in/out, unaffected by the split: storage backends
(`workspace/storage/*`), compute backends (`compute/*`), the workspace
client, `ArtifactService`, and the `init_platform` registry. These are the
natural contents of a shared core package if/when Phase 3 happens.
