# Adding a New Job Type

## Overview

The job system is fully generic. Adding a new job type means writing the job definition and registering its domain — the handler, API, worker, and workflow spec all pick it up automatically.

---

## Core concepts

| Concept | What it is |
|---|---|
| `BaseJobState` | Required base for every graph state. Carries `node_reviews` — the generic slot where human review data is stored keyed by node name. |
| `NodeGate[ReviewT]` | Declares "after node X runs, collect a human review of type `ReviewT` before continuing." Fires on the node that *just ran*, not on a special graph node. |
| `ExecutionPolicy` | A list of `NodeGate`s. Has `validate(graph)` — raises if a gate references a node that doesn't exist. |
| `JobDefinition` | Bundles everything: graph, node registry, deps factory, policy, param schemas. One instance per job type. |
| `run_graph_job` | The single generic job runner. Tracks `prev_node_name` each step, checks policy gates, saves checkpoints with `gated_node`. Never changes. |
| `SENTINEL_DONE` | `"__done__"` stored as `next_node_key` when graph computation is complete but a review hasn't been submitted yet. |

Human-review logic lives **only in the policy** — graph nodes are pure computation.

---

## Steps

### 1. Define state

```python
from ai_platform.jobs.base_state import BaseJobState


class MyState(BaseJobState):  # MUST extend BaseJobState
    input_text: str | None = None
    result: str | None = None
    # human reviews go into node_reviews (inherited) — don't add fields for them
```

### 2. Write graph nodes (pure computation)

```python
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

@dataclass
class ProcessNode(BaseNode[MyState, MyDeps]):
    stage_label = "Process"
    async def run(self, ctx: GraphRunContext[MyState, MyDeps]) -> End[None]:
        ctx.state.result = do_work(ctx.state.input_text)
        return End(None)
```

No human-step logic here. If a node needs the review submitted for a previous node, read it from `ctx.state.get_review("PreviousNode", ReviewType)`.

### 3. Define the review type (if needed)

```python
class MyReview(BaseModel):
    approved: bool
    notes: str
```

### 4. Create the `JobDefinition`

The `JobDefinition` is the single source of truth for a job type — it
bundles the graph, state type, node registry, deps factory, the
`ExecutionPolicy` (which carries the `NodeGate`s), persistence
callbacks, and the typed submit-input / result shapes. The API,
worker, and workflow-spec endpoint all read from it.

Build it inside your domain module. The canonical, current example is
`build_math_qa_job_definition` in
[`src/mathai/math_qa/workflow.py`](../src/mathai/math_qa/workflow.py) —
copy its shape rather than a snippet here, since the constructor
evolves and the live code never goes stale. `policy.validate(graph)`
raises at startup if a gate names a node that isn't in the graph.

### 5. Register the domain

Job types are picked up through their **domain**, not wired
file-by-file. Your domain module exposes a `register(ctx) -> Domain`
function returning a `Domain` that lists its job definitions (and
artifact types) — see [`src/mathai/domain.py`](../src/mathai/domain.py)
for the pattern. Then add that `register` to the `DOMAINS` list in
[`src/ai_platform/composition_root.py`](../src/ai_platform/composition_root.py).

That's the only wiring. The API and worker bootstraps both iterate
`DOMAINS`, so the generic submit endpoint, review endpoint, worker
loop, and `GET /workflows/{job_type}` pick up the new job type
automatically.

---

## API flow

```
POST /jobs/runs/submit
  { "job_type": "my_job", "params": { "input_text": "..." } }
  → 200 { "job_id": "...", "status": "PENDING" }

GET /jobs/{job_id}
  → { "status": "WAITING_INPUT", "stage": "ProcessNode", ... }

GET /jobs/{job_id}/result          # available when WAITING_INPUT or SUCCEEDED
  → { "result": null, "review": null }  ← AI output is here while waiting

POST /jobs/{job_id}/review
  { "params": { "approved": true, "notes": "looks good" } }
  → 200 { "job_id": "...", "status": "PENDING" }

GET /jobs/{job_id}
  → { "status": "SUCCEEDED", "stage": "completed", "percent": 100.0 }
```

---

## Tests

Write unit tests using a dummy graph (no external I/O). See `tests/test_execution_policy.py` for the pattern — `MockExecutor` replaces storage, `@pytest.mark.anyio` handles async.

```
.venv/bin/python -m pytest tests/ -v
```
