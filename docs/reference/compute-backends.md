# Compute backends

How a submitted job reaches the code that runs it. Selected with the
`COMPUTE` env var. Default: `poll`.

| `COMPUTE` | Worker process? | `enqueue` | `start_worker` | When to use |
|---|---|---|---|---|
| `poll` (default) | yes (`scripts/worker.sh`) | no-op | poll loop | what we've always had; safe default |
| `thread` | no — runs in API process | submits to a `ThreadPoolExecutor` | `NotImplementedError` | single-machine dev; sub-second latency, no second process |
| `celery` | yes (`celery -A … worker`) | `run_job.delay(job_id)` | `NotImplementedError` (own CLI) | multi-instance prod with a broker (epic #64, flip-ready not yet default) |

The three are interchangeable from the API's point of view — the
router calls `compute.enqueue(job_id)` after persisting a `JobRecord`
(submit) or after flipping a paused job back to `PENDING` (review).

## The seam

Two methods on `ai_platform.compute.base.ComputeBackend`:

```python
class ComputeBackend(Protocol):
    name: str
    def enqueue(self, job_id: str) -> None: ...
    def start_worker(self, *, worker_id, interval_s, once, should_stop) -> None: ...
```

**`enqueue`** is called from the API right after the job exists in the
repo. Queue-based backends push the work; poll backends are no-op
(workers will discover the record on their next tick anyway).

**`start_worker`** is the long-running consumer entrypoint
(`python -m ai_platform.entrypoints.worker` calls it). Poll backends own the loop
here. Backends that have their own CLI raise `NotImplementedError`
with a message pointing at the right entrypoint instead of silently
running an empty process.

## Wiring

Both the API and the worker bootstrap the same way:

```python
ws       = bootstrap_workspace()                                   # storage
domains  = register_domains(DOMAINS, ws)                           # job defs
compute  = bootstrap_compute(ws.executor, domains.job_definitions) # COMPUTE
```

API then calls `build_api(workspace=ws, domains=domains, compute=compute)`,
which `init_platform`s the DI singletons so every router can
`Depends(get_compute)`.

Worker then calls `compute.start_worker(worker_id=…, interval_s=…, once=…, should_stop=…)`.

## `COMPUTE=poll` — the default

The original model. The API doesn't notify anyone on submit; workers
poll the repo. Run `scripts/api.sh` and `scripts/worker.sh` (or
`scripts/dev.sh` to fan out both). Survives multi-instance deployments
and process restarts because the broker (the repo itself) is durable.

## `COMPUTE=thread` — the surprise

Jobs run in the API process on a `ThreadPoolExecutor`. **No worker
process needed.**

```bash
COMPUTE=thread BACKEND=local ./scripts/api.sh
# submit a job from the UI — it runs immediately, no scripts/worker.sh required
```

Knobs:
- `COMPUTE_THREAD_WORKERS` — pool size (default `4`).

Tradeoffs:
- ✅ Sub-second latency between submit and first node firing.
- ✅ One process, fewer moving parts in dev.
- ❌ In-flight jobs (`status=RUNNING`) are lost if the API restarts —
  nothing reclaims them on boot. That's exactly the case for switching
  to Celery in prod.
- ❌ Doesn't scale across API instances (each pool sees only what its
  own process enqueued).

## `COMPUTE=celery` — broker-backed (being made flip-ready, epic #64)

Wired, not yet the prod default. `enqueue` routes `run_job` to a
**per-runtime queue** — `apply_async(queue=runtime.<runtime>)`, keyed off
the job's `runtime_selector`
([`compute/celery.py`](../../packages/core/src/ai_platform/compute/celery.py));
the consumer is its own CLI, so `start_worker` stays
`NotImplementedError` and redirects operators to it:

```bash
celery -A ai_platform.entrypoints.celery_app worker --loglevel=info
```

The task body
([`celery_app.py`](../../packages/worker/src/ai_platform/entrypoints/celery_app.py))
bootstraps per worker-child (`worker_process_init`, not at import — a
forked prefork pool can't share the master's psycopg FDs): each child opens
its own pool and registers this runtime's domains. The runtime's
CodePackage wheels are pip-installed **once in the main process before the
fork** (`worker_init`), not per child — installing per child raced N pip
processes on the same `site-packages` and corrupted wheels at
`CELERY_CONCURRENCY>=2` (issue #73). Each child then claims the
broker-routed `job_id` and drives its graph. No Celery result backend —
job state lives in Postgres on `JobRecord.state`.

### Per-runtime routing (issue #66)

Prod splits runtimes across worker pools with disjoint dependency stacks
(`default` = pydantic_ai; `crewai` = CrewAI — they can't share one
interpreter). So a single celery pool can't serve every runtime. Instead
there is **one queue + one consumer per runtime**
(`celery_queue_for_runtime(runtime)` → `runtime.<runtime>`): the API
producer routes each job to its runtime's queue, and each consumer
(`WORKER_RUNTIME`) registers only its runtime's domains and consumes only
its own queue — mirroring the poll `worker` / `worker-crewai` split. Run
`celery-worker` (default) and `celery-worker-crewai` (crewai). See
[`hetzner-deploy.md` §6](../operations/hetzner-deploy.md).

### Durability net (issue #67)

Poll has a built-in safety net: the repo *is* the queue, so a PENDING
row is simply rediscovered on the next `claim_next_pending` and a lost
worker self-heals. Celery gives that up — `enqueue()` pushes to Redis
exactly once. A job can then be stranded if the broker is down at
submit, a redis restart drops the message before an AOF flush, or #62's
lease reaper releases a `RUNNING` job back to `PENDING` (nothing
re-pushes it under celery). Two pieces restore the net:

1. **Best-effort submit.** The router persists the `JobRecord` (PENDING)
   *before* `enqueue`, then swallows an enqueue failure
   (`_enqueue_best_effort` in
   [`job_runs.py`](../../packages/api/src/ai_platform/api/routers/job_runs.py)):
   a broker hiccup never 500s the submit and strands the row — the job
   stays PENDING for the reconciler. Same on `/review` resume.

2. **Beat sweep.** `reconcile_jobs`, a celery-beat task, runs two passes
   each tick: reclaim expired leases (RUNNING→PENDING, the reaper poll
   has no loop to host under celery) and re-enqueue any job stuck PENDING
   past a grace window. The re-enqueue goes through the **same per-runtime
   routing** as submit (issue #66): each pool's reconciler is scoped to its
   own runtime's job_types and re-pushes onto its own runtime queue, so a
   re-driven crewai job lands back on the crewai consumer, never the
   default one. Idempotent with live deliveries: only PENDING rows older
   than `CELERY_PENDING_RECONCILE_AGE_S` are re-pushed, and `run_job`
   claims via `claim_job_for_run` (PENDING-gated), so a re-push that races
   the original message no-ops on the second.

The sweep only fires when a beat scheduler runs — embed it with
`celery … worker -B`, or run a dedicated `celery … beat`. Knobs:

- `CELERY_RECONCILE_INTERVAL_S` — sweep cadence (default `60`).
- `CELERY_PENDING_RECONCILE_AGE_S` — min PENDING age before re-enqueue
  (default `120`; keep well above normal sub-second pickup).
- `WORKER_JOB_LEASE_TTL_S` — shared with the poll reaper; unset = no
  lease reap in the sweep.

## Adding another backend

Drop a file in `src/ai_platform/compute/` that implements the
protocol, register it in
[`bootstrap.py`](../src/ai_platform/compute/bootstrap.py), done.
Nothing else changes.

## Tests

`tests/test_job_runs_router.py` pins the contract:

- `test_submit_calls_compute_enqueue_with_job_id`
- `test_review_calls_compute_enqueue_to_resume_run`

Both verify the router hands the job id off to whatever backend is
configured. The real backends are smoke-imported under each
`COMPUTE=` value but not unit-tested individually — they're each ~50
lines of glue around the same `_run_one_job` body that the existing
artifact-persistence tests already cover end-to-end.

The celery durability net (issue #67) is unit-tested at the executor
seam in `tests/test_pending_reconciler.py` (reconcile re-enqueues a
stuck-PENDING job, leaves a fresh/in-flight one alone, the
`claim_job_for_run` idempotency guard drops duplicate deliveries, and a
reaper-reclaimed job is re-enqueued under celery), plus
`test_submit_survives_broker_unavailable_enqueue` /
`test_review_survives_broker_unavailable_enqueue` in
`tests/test_job_runs_router.py` for best-effort submit.
