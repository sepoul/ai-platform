# Live worker → UI logs

Lets graph nodes surface progress to the user in real time. Worker
process emits → API broadcasts → browser renders. **One-way, HTTP
all the way down — no WebSockets.**

---

## The flow

```
graph node
  await ctx.deps.logger.info("…")
            │
            │ httpx POST /jobs/{id}/logs
            ▼
┌──────────────────────────────────┐
│  FastAPI process                 │
│   POST handler →                 │
│   LogBus.publish(entry)          │  in-memory pub/sub
│   ↑                              │  keyed by job_id
│   │ fan out to N subscribers     │
│   ▼                              │
│   GET /jobs/{id}/logs/stream     │  SSE
└──────────────┬───────────────────┘
               │ text/event-stream
               ▼
       ┌──────────────────────┐
       │  Next.js BFF         │  passes the upstream
       │  /api/jobs/.../stream│  Response.body through
       └──────────┬───────────┘
                  │
                  ▼
            EventSource → useJobLogs → <JobLogs>
```

Two browser tabs on the same job both subscribe; the bus fans every
POST to both queues. Slow consumers drop entries (queue cap 256 per
subscriber); never blocks publish.

---

## Why SSE, not WebSocket

Logs are server → client only. SSE is plain HTTP — works through
every proxy, no upgrade dance, no second socket layer in Next.js
(we just pipe `Response.body`). The fanout we DO need (one POST → N
subscribers) lives in `LogBus`, which would look exactly the same on
top of WebSockets — so the transport choice is purely about
simplicity.

---

## Layout

| Where | What |
|---|---|
| [`runtime/log_bus.py`](../src/ai_platform/runtime/log_bus.py) | API-side fan-out — `LogBus.publish` / `subscribe`, `LogEntry` model. **Not** a worker abstraction. |
| [`runtime/worker_log.py`](../src/ai_platform/runtime/worker_log.py) | `WorkerLogger` — what nodes call. Always HTTP-POSTs (works in-process or remote). `NullLogger` for tests. |
| [`api/routers/job_logs.py`](../src/ai_platform/api/routers/job_logs.py) | `POST /jobs/{id}/logs` (worker → API) and `GET /jobs/{id}/logs/stream` (SSE). |
| [`math-ui/app/api/jobs/[jobId]/logs/stream/route.ts`](../math-ui/app/api/jobs/[jobId]/logs/stream/route.ts) | Next.js BFF — streams the upstream SSE body straight through; cancels upstream when client disconnects. |
| [`math-ui/lib/platform/hooks/use-job-logs.ts`](../math-ui/lib/platform/hooks/use-job-logs.ts) | `useJobLogs(jobId, enabled)` — `EventSource` subscription with auto-reconnect. |
| [`math-ui/components/jobs/job-logs.tsx`](../math-ui/components/jobs/job-logs.tsx) | `<JobLogs>` panel — lives next to `<WorkflowJobRunner>` on job pages. |

---

## Emitting from a node

The runner injects `_job_id` into the deps payload; the domain's
`deps_factory` builds a `WorkerLogger` from it:

```python
# in MathQAWorkflowDependencies
@dataclass
class MathQAWorkflowDependencies:
    ...
    logger: WorkerLogger = field(default_factory=NullLogger)

# in build_math_qa_job_definition
def _deps_factory(payload: dict):
    job_id = payload.get("_job_id")
    logger = WorkerLogger(job_id) if job_id else NullLogger()
    return MathQAWorkflowDependencies(..., logger=logger)
```

Inside a node:

```python
async def run(self, ctx):
    log = ctx.deps.logger.for_stage("GenerateAnswerStep")
    await log.info("calling LLM…")
    ...
    await log.info(f"answer received ({len(text)} chars)")
```

`for_stage` returns a child logger tagged with the stage label so
every line carries that context to the UI. Use `.info` / `.warning`
/ `.error` / `.debug` — same names as stdlib logger. Best-effort: if
the API is unreachable, the call drops silently. **Don't** `print(...)`
or roll your own websocket; see
[AGENTS.md](../AGENTS.md#logging-from-a-worker--ui).

---

## Configuration

| Var | Default | What |
|---|---|---|
| `PLATFORM_API_URL` | `http://127.0.0.1:8000` | Where the worker POSTs. Matches `scripts/api.sh` defaults so dev needs no config. Set to `http://api:8000` (or wherever) when the worker isn't on localhost. |

---

## Open followups

- **Multi-instance API.** `LogBus` is per-process. With several API
  workers behind a load balancer, a subscriber on instance A misses
  POSTs that landed on instance B. Swap the bus implementation for
  Redis pub/sub — same `publish` / `subscribe` surface, no caller
  changes.
- **History replay.** Subscribers only see entries published after
  they connect. Refreshing the browser drops the prior log lines. A
  small ring buffer per `job_id` (last N entries) on the bus would
  fix it; not built yet.
- **Schema.** `LogEntry` lives in `runtime/log_bus.py`, not in the
  OpenAPI document (the SSE stream isn't a JSON endpoint). Frontend
  types it manually in `lib/platform/log-types.ts`. Lift into the
  schema if the shape ever drifts.
