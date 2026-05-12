# Adding a New Job Type

## Overview

The job system is fully generic. Adding a new job type means writing **one file** (the job definition) — the handler, API, worker, and workflow spec all pick it up automatically.

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

```python
from ai_platform.jobs.execution_policy import (
    ExecutionPolicy, NodeGate, JobDefinition, JobParam
)

my_graph = Graph(nodes=(ProcessNode,), state_type=MyState)

my_policy = ExecutionPolicy(gates=[
    NodeGate(
        node_name="ProcessNode",  # fires after ProcessNode runs
        review_type=MyReview,
        resume_params=[
            JobParam("approved", "boolean", required=True),
            JobParam("notes", "string", required=False),
        ],
        parse_review=lambda p: MyReview(**p),
    )
])

my_job_def = JobDefinition(
    name="my_job",  # key used everywhere
    graph_ref="my_graph",
    graph=my_graph,
    state_type=MyState,
    start_node_key="ProcessNode",
    node_registry={"ProcessNode": ProcessNode},
    deps_factory=lambda payload, client: MyDeps(**payload),
    policy=my_policy,
    submit_params=[
        JobParam("input_text", "string", required=True),
    ],
    extract_result=lambda s: {"result": s.result, "review": s.node_reviews.get("ProcessNode")},
)
```

Validate at startup (raises if a gate names a node not in the graph):
```python
my_policy.validate(my_graph)
```

### 5. Register in two places

**`src/routers/job_runs.py`** — for the API:
```python
from mymodule import my_job_def
_JOBS[my_job_def.name] = my_job_def
```

**`src/worker.py`** — for the worker:
```python
from mymodule import my_job_def
_JOB_DEFINITIONS[my_job_def.name] = my_job_def
```

**`src/routers/workflows.py`** — for the workflow spec endpoint:
```python
_JOBS[my_job_def.name] = my_job_def
_EDGES["my_job"] = [EdgeResponse(source="ProcessNode", target="End")]
```

That's it. The generic handler, submit endpoint, review endpoint, and `GET /workflows/my_job` all work automatically.

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
