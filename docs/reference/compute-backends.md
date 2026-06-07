# Compute backends

How a submitted job reaches the code that runs it. Selected with the
`COMPUTE` env var. Default: `poll`.

| `COMPUTE` | Worker process? | `enqueue` | `start_worker` | When to use |
|---|---|---|---|---|
| `poll` (default) | yes (`scripts/worker.sh`) | no-op | poll loop | what we've always had; safe default |
| `thread` | no — runs in API process | submits to a `ThreadPoolExecutor` | `NotImplementedError` | single-machine dev; sub-second latency, no second process |
| `celery` | yes (`celery -A … worker`) | `task.delay(job_id)` *(stub)* | `NotImplementedError` | future: multi-instance prod with a broker |

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

## `COMPUTE=celery` — placeholder

Wired but not implemented. Both methods raise `NotImplementedError`
on purpose — setting `COMPUTE=celery` today gets you a clear pointer
to the migration plan in
[`src/ai_platform/compute/celery.py`](../src/ai_platform/compute/celery.py)
rather than a silent fallback.

To finish it:

1. Add `celery` + a broker driver (e.g. `redis`) to `packages/core/pyproject.toml`.
2. Create `execution/celery_app.py` with a `Celery("mathapp", broker=…)`
   instance and a `run_job(job_id)` task that:
   - bootstraps the workspace + domains (same three calls above),
   - fetches the record by id (skip `claim_next_pending` — the broker
     already routed the work),
   - runs the body of `_run_one_job` against that record.
3. In `CeleryComputeBackend.enqueue`, replace the `NotImplementedError`
   with `run_job.delay(job_id)`.
4. Operators run `celery -A execution.celery_app worker` instead of
   `python -m ai_platform.entrypoints.worker`. `start_worker` stays
   `NotImplementedError` — the message redirects them.

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
