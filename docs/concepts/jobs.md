# Jobs platform — implementation reference

The platform's job system runs `pydantic_graph` workflows reliably:
submit → execute step by step → optionally pause for human review →
resume → produce a typed result. This doc captures the
**implemented** shape; for adding a new job type, read
[`onboarding_new_job_type.md`](../guides/deploy-a-domain.md).

---

## At a glance

| Concept | What it is | Where |
|---|---|---|
| `JobRecord` | Storage row carrying `JobSpec` (intent) + `JobState` (status, progress, result preview). | [`structured/job_repository.py`](../src/ai_platform/workspace/storage/structured/job_repository.py) |
| `JobSpec` | Immutable: `job_id`, `job_type`, `input_payload`, `created_at`. | same |
| `JobState` | Mutable: `status`, `stage`, `percent`, `message`, `waiting_for`, `error_message`, `result_payload`. | same |
| `GraphCheckpoint` | Snapshot of `state_data` + `next_node_key` (+ optional `gated_node`/`reason`). Stored separately so resumption is cheap. | [`graph_execution.py`](../src/ai_platform/jobs/graph_execution.py) |
| `JobDefinition` | Single source of truth per job type — graph, node registry, deps factory, policy, persistence callbacks, typed input/result. | [`jobs/execution_policy.py`](../src/ai_platform/jobs/execution_policy.py) |
| `ExecutionPolicy` | List of `NodeGate`s. Fires *after* the named node runs to collect a typed human review. | same |
| `run_graph_job` | Generic runner. Reads checkpoint or starts fresh, drives `graph.iter`, pauses on gates, persists artifacts via `PersistencePolicy`. Never changes per domain. | [`jobs/job_runner.py`](../src/ai_platform/jobs/job_runner.py) |
| `SENTINEL_DONE` | `"__done__"` — stored as `next_node_key` when computation is complete but a review is still pending. | same |

---

## Lifecycle

```
                ┌─────────────────────────┐
   POST submit  │ JobRecord(PENDING)      │
   ───────────► │ + GraphCheckpoint @ start│
                └────────────┬────────────┘
                             │ enqueue (compute backend dispatches)
                             ▼
                ┌─────────────────────────┐
                │ run_graph_job:          │
                │  graph.iter from        │
                │  checkpoint             │
                └────┬────────────────┬───┘
                     │                │
            no gate  │                │ gate hit on prev_node_name
                     ▼                ▼
            ┌──────────────┐   ┌──────────────────────────┐
            │ End → result │   │ JobRecord(WAITING_INPUT) │
            │ SUCCEEDED    │   │ checkpoint w/ gated_node │
            └──────────────┘   └────────────┬─────────────┘
                                            │ POST /jobs/{id}/review
                                            ▼
                                  ┌──────────────────────┐
                                  │ state.set_review(...)│
                                  │ enqueue → resume     │
                                  └──────────────────────┘
```

States: `PENDING` → `RUNNING` → (`WAITING_INPUT` ↔ `RUNNING`)* →
`SUCCEEDED` | `FAILED` | `CANCELLED`.

---

## Storage backends

Three implementations of the
[`JobRepository`](../src/ai_platform/workspace/storage/protocols.py)
Protocol — `LocalJobRepository`, `B2JobRepository`,
`SupabaseJobRepository` — selected by the `BACKEND` env var through
[`workspace/storage/backends.py`](../src/ai_platform/workspace/storage/backends.py).
The contract is row-shaped: `put` (with optional `expected_version`
for optimistic concurrency on Postgres), `get`, `list(status, job_type, limit)`,
`delete`. The repo is also the source of truth for filtering on the
`GET /jobs` endpoint (status / job_type / created_after / limit /
offset).

Full breakdown including the Supabase schema and what the contract
unlocks: [`storage_backends.md`](../reference/storage-backends.md).

---

## Compute backends

`COMPUTE` env var picks how a submitted job reaches code that runs
it: `poll` (default — separate worker process), `thread` (in-process
pool), `celery` (stub). The router calls `compute.enqueue(job_id)`
right after the record is created or unpaused; that's the only seam.
See [`compute_backends.md`](../reference/compute-backends.md) for full details.

---

## Human review gates

Reviews are **not** graph nodes. The domain declares them in its
`ExecutionPolicy`:

```python
math_qa_policy = ExecutionPolicy(
    gates=[NodeGate(node_name="GenerateLatexStep", review_type=UserComment)]
)
```

`run_graph_job` tracks `prev_node_name` after each step; when a gate
matches and the state has no review for that node yet, the runner:

1. Calls `PersistencePolicy.on_pause` (mints any artifacts produced
   so far).
2. Saves a checkpoint with `next_node_key` = the node that *would*
   run next (or `SENTINEL_DONE` if the graph is at `End`),
   `gated_node` = the node that just ran.
3. Updates the record to `WAITING_INPUT` with `waiting_for` = the
   gate's `review_type` name.

The UI fetches the result preview via `GET /jobs/{id}/result`,
collects the review, and POSTs to `/jobs/{id}/review`. The runner
re-enters: on resume it sees `state.has_review(prev_node_name)`,
skips the gate, and continues.

`is_human_step` on `WorkflowSpecResponse.stages[]` is policy-derived;
the workflow viewer renders it without heuristics. See
[NEXT_BEST_STEPS §1d](../NEXT_BEST_STEPS.md#1d-surface-executionpolicy-on-workflowspecresponse--done).

---

## Artifacts as outputs

Domains mint typed `BaseArtifact` subclasses inside their
`PersistencePolicy.on_complete` / `on_pause`. The IDs land on
`state.artifact_refs`; `JobDefinition.fetch_result` rebuilds the
typed result by hydrating those refs from the workspace's
`ArtifactService`. The `GET /artifacts/...` endpoints expose them
as a discriminated union — see
[NEXT_BEST_STEPS §1c](../NEXT_BEST_STEPS.md#1c-promote-artifacts-router-to-ai_platform--done).

---

## API surface

Generated from the live FastAPI app (use
[`scripts/dump-openapi.sh`](../scripts/dump-openapi.sh) for the full
schema):

| Path | Purpose |
|---|---|
| `POST /jobs/runs/submit` | Submit a typed job. Body is a discriminated union over every registered `submit_input_type`. |
| `GET /jobs` | List with filters (`status`, `job_type`, `created_after`, `created_before`, `limit`, `offset`). |
| `GET /jobs/{job_id}` | Status snapshot — `JobStatusResponse` with progress fields + result preview. |
| `GET /jobs/{job_id}/result` | Typed result — discriminated union over every registered `result_type`. |
| `POST /jobs/{job_id}/review` | Submit a human review. Body is the union of every gate's `review_type`. |
| `POST /jobs/{job_id}/logs` | Worker → API log emission (used by `WorkerLogger`). See [`live_logs.md`](../guides/live-logs.md). |
| `GET /jobs/{job_id}/logs/stream` | SSE: live log stream for one job. |

---

## Invariants we rely on

- `JobSpec` is immutable; everything mutable lives on `JobState` and
  `GraphCheckpoint`.
- The same `job_id` always lands on the same record; we use it as
  the key for compute-backend dispatch, log-bus topics, and
  workspace artifacts.
- A graph node's `__name__` is the canonical key for checkpointing
  and gate matching. Renaming a node is a breaking change for jobs
  in flight at the moment the rename ships.
- Gates fire **after** the node runs, never before. State-side
  invariant: `state.has_review(prev_node_name)` flips a paused job
  back to `RUNNING`.
- Logs are best-effort. Drop on the floor when the per-subscriber
  queue overflows or the API is unreachable; never block the worker.

---

## Open followups

- `idempotency_key` exists on `JobSpec` but isn't honored end-to-end
  yet — see
  [NEXT_BEST_STEPS §2](../NEXT_BEST_STEPS.md#2-honor-idempotency_key-on-submission).
- Worker crash recovery: leases / heartbeats are designed for but
  not implemented (poll backend currently re-runs from the last
  saved checkpoint, which is good enough for dev).
- Multi-instance API: the `LogBus` is per-process — see
  [`live_logs.md`](../guides/live-logs.md) for the Redis swap-in plan.
