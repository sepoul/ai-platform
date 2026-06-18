# Notes for coding agents

If you're an AI assistant editing this repo (including the in-tree
`math-ui/` frontend), read this first. It's a short list of red flags
that have actually happened and the right way to do the thing instead.
The detailed docs are linked at the end.

---

## Layout

| Path | Role |
|---|---|
| `src/`, `instructions/`, `scripts/` | FastAPI backend, Python workers, job/graph definitions |
| `math-ui/` | Next.js 16 frontend (was a sibling repo until 2026-05-16; merged in) |

The contract between them is the **OpenAPI schema** that FastAPI
emits. See [`docs/dev_lifecycle.md`](../reference/typed-clients.md) for the
regenerate-and-typecheck loop.

Layering:

- `ai_platform.*` (in `packages/core/`) — generic platform: jobs,
  workflows, prompts, artifacts, compute. **Never imports from a
  domain.**
- `mathai.*` — every domain ships in its own package under `packages/`:
  - `packages/math-qa/` contributes `mathai.math_qa.*` (default runtime).
  - `packages/math-conversation/` contributes `mathai.math_conversation.*`
    (crewai runtime).
  - `packages/core/` contributes `mathai.workspace.*` (cross-domain
    facade — `MathWorkspaceClient`, `MathArtifactService`).
  Each domain plugs into the platform via `Domain.register()`. The
  three contribute to the `mathai` PEP-420 namespace; nothing imports
  a domain across the boundary at module load.
- `math-ui/lib/platform/` — generic platform primitives in TS.
- `math-ui/lib/domains/<domain>/` — domain-specific TS shapes/clients.

If you're tempted to put something domain-specific in `ai_platform`
or vice versa, stop and reconsider. If you're tempted to import one
domain from another (e.g. `from mathai.math_qa.* import X` inside
`mathai.math_conversation.*`), absolutely stop — that breaks the
slim-runtime isolation. Any cross-domain need belongs in
`mathai.workspace.*` (cross-domain facade) or, more likely, in
`ai_platform.*` (truly platform-tier).

---

## Red flags (don't do these)

### Inline prompt strings in graph nodes

**Wrong:**
```python
agent = basic_agent(
    instructions="You are a math tutor. Solve the question step by step.",
    output_type=GeneratedAnswer,
)
```

**Right:** prompts live as Markdown files under
`instructions/<domain>/<name>.md` and are registered in
[`src/ai_platform/ai/prompts/registry.py`](src/ai_platform/ai/prompts/registry.py)
(`PROMPT_DEFINITIONS`). They're deployed via
`scripts/deploy_prompts.py` and editable through the `/prompts` API
(versioned, with execution tracking). Threadthem through the graph
via `WorkflowDependencies` populated by `deps_factory` — see
[`src/mathai/math_qa/workflow.py`](src/mathai/math_qa/workflow.py)
(`_load_prompt`, `MathQAWorkflowDependencies.{answer,latex}_instructions`).

If you write a new agent, the prompt is a registry artifact, not a
string literal in a `.py` file. See
[`docs/prompt_registry.md`](../guides/prompts.md).

### Hand-rolling TypeScript types from FastAPI shapes

**Wrong:** writing `interface JobStatusResponse { ... }` by hand in
`math-ui/lib/`.

**Right:** every server type lives in `math-ui/lib/api/schema.d.ts`,
generated from the FastAPI `/openapi.json` via
`math-ui/scripts/gen-api.sh`. Domain-facing aliases derive from the
schema (see `lib/platform/job-types.ts`,
`lib/domains/math-qa/types.ts`). After any backend response-model
change, run `npm run gen:api` in `math-ui` and commit the diff.

### Domain code in the platform router/registry

**Wrong:** mounting `/workspace/artifacts` from inside `mathai/api/...`
(this happened — fixed in §1c of `NEXT_BEST_STEPS.md`).

**Right:** if a router serves a generic concern (artifacts, jobs,
workflows, prompts), it lives in `ai_platform/api/routers/`. Domains
declare what they bring (`Domain.artifact_types`, `Domain.job_definitions`)
and the platform aggregates. Hardcoded domain knowledge in platform
code is a layering violation.

### Hand-rolling UI patterns instead of `components/library/`

The math-ui has a two-tier component system:

1. `components/ui/` — shadcn primitives (`Card`, `Badge`, `Alert`,
   `Skeleton`, `Tabs`, …). Add more via
   `npx shadcn@latest add <name>`.
2. `components/library/` — app-level patterns layered on top
   (`PageContainer`, `PageHeader`, `Section`, `LoadingCard`,
   `ErrorCard`, `EmptyCard`, `LinkCard`, `FieldList`, `Markdown`,
   `Latex`).

Don't author bespoke `<Card><CardContent>...</CardContent></Card>`
blocks for loading/error/empty states. Don't add new CSS classes to
`app/globals.css`. If a pattern repeats, put it in
`components/library/` and re-export from `index.ts`.

### Skipping codegen / openapi loop

After any change to a request/response model:

1. Run `mathapp` tests: `scripts/test.sh`.
2. From `math-ui/`: `npm run gen:api`. Commit `lib/api/schema.d.ts`.
3. From `math-ui/`: `npx tsc --noEmit`. Fix consumers.
4. `npx next build` to confirm route compilation.

CI runs `npm run gen:api:check` (regenerate + `git diff --exit-code`)
to catch missing regenerations.

**⚠️ Post repo-split SDK regen caveat.** The typed contract now lives in
`sdk-ts/src/schema.d.ts` (published as `@aiplatform/sdk`, consumed by
both `platform-ui/` here and `math-app/math-ui`). Regenerating it
(`sdk-ts: npm run gen:api`) is **only safe from an OpenAPI dump of a
deployment that registers every domain whose types consumers need**.
This repo's local API boots only the synthetic `_demo` domain, so a
naive local regen silently **drops the `math_*` types `math-app/math-ui`
imports** — the diff will show large deletions. If your change is
platform-only (new route / response model that needs no domain), it's
fine to land the backend + tests and let the schema be regenerated at
deploy time against the full platform+math OpenAPI; do **not** commit a
local regen that deletes domain types. See the warning block in
`sdk-ts/scripts/gen-api.sh`.

### Reaching for `os.getenv` inside a node

Workers and API processes load env via the bootstrap helpers
(`bootstrap_workspace`, `bootstrap_compute`). New configuration goes
through there. Inline `os.getenv` calls scattered through nodes /
clients / tools split the configuration surface. The one acceptable
exception is small server-to-server tool URLs (e.g.
`UI_TOOL_API_URL` for the LaTeX validator).

### Logging from a worker → UI

When a graph node wants to surface live progress to the UI, use
`ctx.deps.logger.info(...)` (or `.warning` / `.error` / `.debug`) — the
domain's `deps_factory` builds a `WorkerLogger` from the runner-injected
`_job_id`. Don't `print(...)` and don't roll your own websocket.

Plumbing:
[`ai_platform.runtime.log_bus`](src/ai_platform/runtime/log_bus.py)
broadcasts to every subscriber on
[`GET /jobs/{id}/logs/stream`](src/ai_platform/api/routers/job_logs.py)
(SSE, not WebSockets — logs are one-way and SSE is just HTTP). Browser
subscribes via
[`useJobLogs`](math-ui/lib/platform/hooks/use-job-logs.ts) →
[`<JobLogs>`](math-ui/components/jobs/job-logs.tsx).

### Forgetting to register a new artifact type

If you mint a new `BaseArtifact` subclass:

1. Add it to the domain's `artifacts.py` and to its
   `MATH_QA_ARTIFACTS` (or equivalent) registry.
2. Make sure the domain's `register()` includes it in
   `Domain(artifact_types=[...])` — the platform aggregates this and
   wires the discriminated union for `GET /artifacts/{id}`.
3. Update `_persist` / `_extract_result` / `_fetch_result` in the
   domain's workflow factory.
4. Frontend will pick up the new variant on the next `gen:api` and
   `Artifact` becomes a wider union automatically. Add a case to
   `components/artifacts/artifact-card.tsx` if you want a
   domain-specific renderer (otherwise it falls back to a JSON dump
   — see `NEXT_BEST_STEPS.md §7b`).

### Pointing local `docker compose` at prod Supabase

`.env`'s `BACKEND` decides which storage + DB the `api`/`worker`
containers bind to, and `docker compose` reads `.env` at container
**create** time:

- `BACKEND=local` → the in-container `/data` FS volume (`mathapp-data`).
  **This is the default for laptop dev — keep it here.**
- `BACKEND=supabase` → the **shared PROD Supabase** (live DB + the
  `app-data` storage bucket). With this set, `docker compose up` /
  `restart` boots an api + worker that **poll and process real PROD jobs
  from your laptop** and read/write prod storage. Tell-tale: the worker
  boot log shows `httpx … GET https://<proj>.supabase.co/storage/…`.

So before any `docker compose up` / `restart`, confirm the target:

```bash
grep '^BACKEND' .env                       # expect: BACKEND=local
docker compose exec worker printenv BACKEND  # what's actually running
```

Only set `supabase` for a deliberate live run. And note: `docker compose
restart` does **not** re-read `.env` — after editing it you must
`docker compose up -d worker worker-crewai` (the `crewai` pool is behind
the `crewai` profile) to recreate the containers with the new env.

---

## How to verify a change

Backend:

```bash
PYTHONPATH=src BACKEND=local LOCAL_DATA_DIR="$PWD/mathdata" \
  .venv/bin/python -m pytest tests/ -x -q
```

Quick OpenAPI smoke (no server needed):

```bash
./scripts/dump-openapi.sh /tmp/openapi.json
jq '.paths | keys' /tmp/openapi.json
```

Frontend (from `math-ui/`):

```bash
npm run gen:api          # if backend models changed
npx tsc --noEmit
npx next build           # full route compilation
npm run lint             # has 5 pre-existing errors; ignore those
```

For UI changes, also start `npx next dev -p 3000` and click through
the affected route. The lint pre-existing errors are tracked in
`use-job-polling.ts` / `use-active-job.ts`; new errors are real.

---

## Tracking files

- [`NEXT_BEST_STEPS.md`](NEXT_BEST_STEPS.md) — single backlog,
  backend items first then a `Frontend (math-ui/)` section. ✅-done
  entries stay (with a one-paragraph "what landed" note).
- [`FEATURES.md`](FEATURES.md) — directional ideas, not committed
  designs.

When you finish a substantive change, mark the relevant tracking
entry done (with a one-paragraph "what landed" note); don't delete
the entry.

---

## Further reading

The whole `docs/` set is also browsable as a website — run
`./scripts/docs.sh` and open <http://127.0.0.1:8001>. Material
theme, full-text search, live reload. Index at
[`docs/README.md`](docs/README.md).

- [`docs/dev_lifecycle.md`](../reference/typed-clients.md) — codegen loop,
  cross-repo coherence.
- [`docs/onboarding_new_job_type.md`](../guides/deploy-a-domain.md)
  — adding a new domain workflow.
- [`docs/jobs_spec.md`](../concepts/jobs.md) — platform job lifecycle,
  checkpoints, gates, invariants.
- [`docs/prompt_registry.md`](../guides/prompts.md) — prompt
  registry, deployment, execution tracking.
- [`docs/live_logs.md`](../guides/live-logs.md) — worker → UI SSE log
  stream.
- [`docs/compute_backends.md`](../reference/compute-backends.md) — poll /
  thread / celery selection.

If you see a pattern that "feels off" — it probably is. Surface it
to the human reviewer before committing.
