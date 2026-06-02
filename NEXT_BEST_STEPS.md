# Next best steps

Ideas to push the platform forward, ordered by leverage. Anything worker-
internal (concurrency, retries, reapers) is intentionally absent — that
surface will be replaced by Celery, no point hardening the polling loop.

Backend items use plain numbering (§1, §2, …). Frontend items live
under the "Frontend (`math-ui/`)" section at the bottom and are
referenced as "Frontend §N" to disambiguate from backend numbering.

---

## 0. Deploy pipeline — CI image build → GHCR → box pull ✅ done

GitHub Actions
([.github/workflows/build-image.yml](.github/workflows/build-image.yml))
builds on push to `main` and on `workflow_dispatch`, tagging
`ghcr.io/sepoul/mathapp:latest` + `:sha-<short>`. The GHCR package is
public — the box pulls anonymously, no PAT on disk.
[`docker-compose.prod.yml`](docker-compose.prod.yml) overrides each
service's `image:` to the GHCR path; the base file's `build:` is
merged in but ignored by `pull`.
[`infra/hetzner/scripts/redeploy.sh`](infra/hetzner/scripts/redeploy.sh)
collapses redeploy to `compose pull && compose up -d && image prune`.

Validated end-to-end on the live CX23: cold-deploy from an empty box
(clone repo → scp `.env` → `redeploy.sh`) brought API + worker up in
under a minute with no build toolchain involved. `/jobs` returned
real records from Supabase. Box-side secret-handling and the
`.env` rotation flow are written up in `local/security.md`
(gitignored — local-only notes).

Open question still standing: whether `infra/` graduates to its own
repo. `mathapp` and `math-ui` are siblings; a top-level
infra/packaging repo that builds and ships both is the natural home
once the deploy story grows past one service. Not now — noted.

## 1. TypeScript codegen pipeline ✅ done

Implemented in [scripts/dump-openapi.sh](scripts/dump-openapi.sh) +
[math-ui/scripts/gen-api.sh](math-ui/scripts/gen-api.sh). See
[docs/dev_lifecycle.md](docs/dev_lifecycle.md) for the loop.

## 1b. `GET /workflows` listing endpoint ✅ done

Implemented in [api/routers/workflows.py](src/ai_platform/api/routers/workflows.py)
and wired up in [math-ui/app/workflows/page.tsx](math-ui/app/workflows/page.tsx);
the `WORKFLOW_JOB_TYPES` constant has been dropped on the frontend.

## 1o. Math QA figures end-to-end ✅ done

The Munkres/Lee/Tu figure pipeline is wired from agent to UI:

- New `FigureArtifact` (`{template, spec: dict, validation_attempts}`)
  registered in `MATH_QA_ARTIFACTS`. `MathQAResult.figure` carries it
  through hydration (`_persist` / `_extract_result` / `_fetch_result`).
- New graph nodes:
  - **`DecideFigureStep`** — control-logic classifier. Haiku call,
    no system instructions (one-sentence message, structured boolean
    output). Best-effort: a classifier failure skips the figure
    rather than failing the job.
  - **`RenderFigureStep`** — pydantic-ai agent with the
    `validate_figure` tool, instructions pulled from
    `math_qa.figure` (with the three scratchpad examples baked in as
    few-shot). Loops on tool feedback until structurally valid.
- Topology branches:
  `GenerateAnswer → DecideFigure → (RenderFigure → GenerateLatex | GenerateLatex)`.
  Edges declared so `WorkflowSpecResponse` shows both arms; review
  gate stays on `GenerateLatexStep` so the user reviews
  text + figure (when present) + LaTeX together.
- Every node logs its phase via `ctx.deps.logger.for_stage(...)` so
  the live `<JobLogs>` panel shows e.g. "calling LLM…", "figure
  decision: YES", "figure validated (template='manifold-chart',
  N attempt(s))".
- Frontend: `MathQAResult.figure` flows through the regenerated
  schema; `<Figure>` renders inside `ResultDisplay` and `<ArtifactCard>`.

## 1k. Browsable docs site ✅ done

`./scripts/docs.sh` boots a Material-themed
[mkdocs](mkdocs.yml) site at <http://127.0.0.1:8001> (port 8001 to
stay clear of the FastAPI 8000). Three nav sections — Architecture,
Onboarding, Project — plus an auto-generated **Reference** tree
that walks `src/` and renders every module's docstrings via
`mkdocstrings`. Generation is one
[`docs/gen_ref_pages.py`](docs/gen_ref_pages.py) script + the
`mkdocs-gen-files` / `mkdocs-literate-nav` plugins; new modules
appear in the sidebar on the next save. The Project section uses
symlinks under `docs/project/` so `AGENTS.md` / `FEATURES.md` /
`NEXT_BEST_STEPS.md` (this file) and the math-ui backlog show up
without copy drift.

## 1l. Docstring rollout 📝 open

The reference tree exists; most module bodies are thin. Worth a
sweep — module-level docstrings explaining "why this exists, what
it depends on, what calls it" beat per-symbol docstrings nine times
out of ten. Highest-leverage targets:

- `ai_platform/jobs/` (executor, runner, execution_policy, base_state)
- `ai_platform/runtime/` (registry, log_bus, worker_log)
- `ai_platform/workspace/storage/` (the structured + blob repos)
- `ai_platform/api/routers/*` (the public HTTP surface)

Every symbol with a body that isn't a one-liner should be visible
in the reference site. When CI gets a docstring coverage gate, this
is the natural baseline.

## 1m. `deploy_prompts.py --update` 📝 open

The deploy script is get-or-create — drift between
`instructions/<domain>/<name>.md` and the stored prompt isn't
auto-resolved. Manual one-off via `update_instructions` works (see
[`docs/prompt_registry.md`](docs/prompt_registry.md#updating-an-existing-prompt)).
A `--update` flag that diffs the file body against the registry and
calls `update_instructions` (which bumps the patch version) when
they differ closes the loop.

## 1n. mkdocs strict mode + `repo_url` 📝 open

The site builds non-strict because docs link into source paths
(`../src/...`) and other repo-root files. Once we set a `repo_url`
in `mkdocs.yml`, a small markdown hook can rewrite those into
absolute GitHub URLs, restoring strict mode. Catches broken nav at
build time; fixes the rendered links so the served reference cards
have working "view source" buttons.

## 1j. Worker → UI live log stream ✅ done

[`WorkerLogger.emit`](src/ai_platform/runtime/worker_log.py) now POSTs
to `${PLATFORM_API_URL}/jobs/{id}/logs` (default
`http://127.0.0.1:8000`, matches `scripts/api.sh`'s defaults so
zero-config in dev). The API's `log_bus` receives it and fans out to
every SSE subscriber — works whether the worker shares a process with
the API or runs separately via `scripts/worker.sh`. Best-effort: any
HTTP error is swallowed so a missing log never fails the worker. Live
smoke verified cross-process delivery (separate Python invocation →
API SSE subscriber, ~50ms latency).

Followups still standing for later:

New platform plumbing for live worker logs:

- [ai_platform/runtime/log_bus.py](src/ai_platform/runtime/log_bus.py)
  — in-memory pub/sub keyed by `job_id` with per-subscriber asyncio
  queues; `publish` is a function call so the in-process worker
  doesn't pay an HTTP roundtrip.
- [ai_platform/runtime/worker_log.py](src/ai_platform/runtime/worker_log.py)
  — `WorkerLogger` and `NullLogger` so node code is just
  `await ctx.deps.logger.info("…")`.
- [ai_platform/api/routers/job_logs.py](src/ai_platform/api/routers/job_logs.py)
  — `POST /jobs/{id}/logs` (used by future remote workers) and
  `GET /jobs/{id}/logs/stream` (SSE — pure HTTP, no WebSocket dance).
- [job_runner.py](src/ai_platform/jobs/job_runner.py) injects
  `_job_id` into the deps payload so domain `deps_factory`s can
  build per-run loggers.
- math_qa nodes now emit a "hello from worker" line in
  `ReceiveQuestionStep` plus stage-by-stage progress lines through
  `GenerateAnswerStep` and `GenerateLatexStep`.

Frontend:

- [`/api/jobs/[jobId]/logs/stream`](math-ui/app/api/jobs/[jobId]/logs/stream/route.ts)
  is a streaming Next.js BFF route that pipes the upstream SSE body
  straight to the browser.
- [`useJobLogs`](math-ui/lib/platform/hooks/use-job-logs.ts)
  subscribes via `EventSource`, with an `enabled` flag so terminal
  jobs stop holding the connection open.
- [`<JobLogs>`](math-ui/components/jobs/job-logs.tsx) renders next
  to the workflow runner on the math_qa job page — auto-scrolls when
  the user is near the bottom, badges for live / reconnecting / idle,
  level + stage tags per row.

Followups (not blocking):

- The SSE endpoint is per-connection in-memory — multi-instance
  FastAPI will need Redis pub/sub behind the same `log_bus.publish`
  surface.
- No history replay — subscribers only see logs after they connect.
  Add a small ring buffer per `job_id` if we want refresh-survives-
  history behavior.
- `LogEntry` isn't part of the OpenAPI document yet (the SSE stream
  isn't a JSON endpoint). The frontend types it manually in
  `lib/platform/log-types.ts`. Lift into the schema if it ever
  matters.

## 1i. `validate_latex` accepts mixed markdown ✅ done

The tool was sending whole markdown answers (with `# Title`, prose,
LaTeX delimiters) straight to KaTeX, which choked on the prose.
Rather than constrain the agent to bare LaTeX, the validation route
now splits on `\(...\)` / `\[...\]` and validates each math segment
independently. New `mode="document"` (default) on
[/api/tools/validate-latex](math-ui/app/api/tools/validate-latex/route.ts);
old `inline` / `block` modes still work for bare-expression callers.
On failure the response includes `segment` + `segment_index` so the
agent can locate the exact bad snippet. Prompt
[`math_qa.latex_render`](instructions/math_qa/latex_render.md) bumped
to v0.1.1 to describe the new behavior. The frontend
[`/latex` playground](math-ui/app/latex/page.tsx) now uses the same
mode and surfaces the failing segment.

When `RichContentArtifact` lands per
[FEATURES.md](FEATURES.md), this validator stays — it just runs
against the `*_latex` segments of a structured payload instead of
splitting a markdown blob.

## 1h. Math QA prompts moved into the registry ✅ done

Both `GenerateAnswerStep` and `GenerateLatexStep` previously inlined
their instructions as string literals in
[workflow.py](src/mathai/math_qa/workflow.py). They now live as
versioned files under
[instructions/math_qa/](instructions/math_qa/) (`answer.md`,
`latex_render.md`) registered in
[ai_platform/ai/prompts/registry.py](src/ai_platform/ai/prompts/registry.py).
`MathQAWorkflowDependencies` carries `answer_instructions` and
`latex_instructions`, populated by `deps_factory` via the
`PromptRegistry`. Editing prompts no longer touches workflow code —
update the `.md` files (or via the `/prompts` API) and bump the
version. Bonus fix: `scripts/deploy_prompts.py` was reaching for
`client.prompt_registry` but the registry actually lives at
`client.platform_client.prompt_registry`; corrected.

This pattern (registry + deps_factory) is the right shape for any
new agent in any domain. See [AGENTS.md](AGENTS.md) for the rule.

## 1g. LaTeX-validated math answer ✅ done (initial slice)

`GenerateLatexStep` is now part of the math_qa graph
(`ReceiveQuestionStep → GenerateAnswerStep → GenerateLatexStep → End`).
A pydantic-ai agent uses the new
[mathai/math_qa/tools.py](src/mathai/math_qa/tools.py) `validate_latex`
tool — which POSTs to `math-ui`'s `/api/tools/validate-latex` (KaTeX
with `throwOnError: true`) — and loops until the tool reports
`valid: true`. Output lands as a `LatexAnswerArtifact` carrying
`latex_source` + `validation_attempts`. The human-review gate moved
to `GenerateLatexStep` so the user sees text + typeset together.

Frontend: KaTeX rendering via a new
[components/library/latex.tsx](math-ui/components/library/latex.tsx)
that splits `\(...\)` / `\[...\]` segments. Used by `ArtifactCard`
(latex_answer case), `ResultDisplay` (typeset answer section), and
`ReviewForm`.

Env var: backend reads `UI_TOOL_API_URL` (default
`http://localhost:3000`) for the validation hop. Set it on workers
when math-ui isn't on localhost.

Follow-ups tracked in
[FEATURES.md](FEATURES.md) (LaTeX correctness bullet) — promoting
this to a generic `LatexCompileGate` once `RichContentArtifact`
lands.

## 1f. Job-history index ✅ done

`JobStatusResponse` gained `job_type` and `created_at` so the UI can
render a domain-agnostic job list. The math-ui
[/jobs](math-ui/app/jobs/page.tsx) page consumes
`GET /jobs` directly and groups runs by status. No additional backend
endpoint needed — `/jobs` already supported the filter/limit/offset
shape.

## 1e. First-class artifact-type registry ✅ done

`GET /artifacts/types` ([api/routers/artifacts.py](src/ai_platform/api/routers/artifacts.py))
returns every registered `BaseArtifact` subclass projected into an
`ArtifactTypeSpec` — `{artifact_type, class_name, domain, fields[]}`
where `fields` is the pydantic schema converted via the new shared
[api/pydantic_fields.py](src/ai_platform/api/pydantic_fields.py)
helper (also reused by the workflows router for submit/resume params).
`DomainsBootstrap` now tracks `artifact_owners: dict[str, str]` so the
registry can attribute each type to its declaring domain. The
math-ui [/artifact-types](math-ui/app/artifact-types/page.tsx) page
renders the registry as first-class platform metadata, parallel to
`/workflows`.

## 1d. Surface `ExecutionPolicy` on `WorkflowSpecResponse` ✅ done

`WorkflowSpecResponse.gates: list[GateSpec]` now flattens
[ExecutionPolicy](src/ai_platform/jobs/execution_policy.py) onto the
spec endpoint — each entry carries `{node_name, review_type, params}`.
The math-ui [WorkflowSpecView](math-ui/components/workflow/workflow-spec-view.tsx)
renders gates as a first-class section; the frontend's old
`waiting_for` string heuristic in `resolveWorkflowStepStates` was
dropped in favour of policy-derived `stage.is_human_step`.

## 1c. Promote artifacts router to `ai_platform` ✅ done

Migrated from `mathai/api/routers/math_qa.py` (which mounted at
`/workspace/artifacts` with no response model) to
[api/routers/artifacts.py](src/ai_platform/api/routers/artifacts.py).
The GET endpoint now serializes a discriminated union over every
registered domain's `BaseArtifact` subclasses, built at startup from
`Domain.artifact_types` aggregated by `register_domains`. The shared
`ArtifactService` lives on `WorkspaceBootstrap` and is exposed to
routers via `runtime/registry.get_artifact_service`. List endpoint
gained `job_id` / `artifact_type` / `limit` filters and returns
lightweight `ArtifactSummary` rows. Frontend viewer at
[math-ui/app/artifacts](math-ui/app/artifacts/page.tsx).

## 2. Honor `idempotency_key` on submission

[JobSpec.idempotency_key](src/ai_platform/workspace/storage/structured/job_repository.py)
exists but no code checks it. To wire it end-to-end:

- Add an optional `idempotency_key` field on `BaseJobInput` so it rides
  in on the same body as the typed input.
- Thread it through `GraphJobExecutor.submit_graph_job` →
  `B2JobRepository.create_job` → `JobRecord.create` so it lands on `spec`.
- In [POST /jobs/runs/submit](src/ai_platform/api/routers/job_runs.py),
  before creating, scan for an existing record with the same
  `(job_type, idempotency_key)` and return its `job_id` if found
  (`list_jobs` already filters by `job_type`).

Avoids the classic "user double-clicks submit" bug and survives the
Celery move because the key lives on the spec, not on the worker.

## 3. Storage tests for `SingleStoreMixin`

The new generic mixin in
[src/ai_platform/workspace/storage/mixins.py](src/ai_platform/workspace/storage/mixins.py)
unifies three call sites and has zero direct test coverage. A small
`tests/test_single_store_mixin.py` exercising put / get / list /
get_all / delete against an in-memory fake `CanonicalRepository` would
lock the contract before more domains inherit from it. Especially
relevant now that every artifact type routes through this mixin.

## 4. Move `src/scripts/` into `ai_platform.scripts`

`src/scripts/{deploy_prompts,generate_workflow_specs}.py` are runtime
entrypoints — same role as `ai_platform.entrypoints.{api,worker}` but for
one-shot CLI tasks. They belong under `ai_platform.scripts` so the runtime
shell owns all entrypoints in one place. Touches `scripts/deploy-prompts.sh`
and any docs referencing the old paths.

## 5. Centralize `_utc_now`

Three modules each define a private `_utc_now()` returning
`datetime.now(timezone.utc)`. Collapse into `ai_platform.utilities.time.utc_now`
so deterministic-clock injection (when we eventually need it for tests
or audit logs) has a single seam. Tiny, but worth folding into whichever
storage session touches the artifact / prompt models.

## 6. Supabase backend integration ✅ done

Supabase added as a third storage backend (Postgres for structured
records, Supabase Storage for blobs). Branch `supabase-backend`,
plan + decisions in
[docs/project/supabase_intro.md](docs/project/supabase_intro.md).
What landed:

- Row-shaped `JobRepository` / `ArtifactRepository` /
  `PromptRepository` / `PromptExecutionRepository` Protocols in
  [src/ai_platform/workspace/storage/protocols.py](src/ai_platform/workspace/storage/protocols.py).
  `SingleStoreMixin` / `_JobStoreMixin` are now backend-private.
- `Backend` factory in
  [src/ai_platform/workspace/storage/backends.py](src/ai_platform/workspace/storage/backends.py)
  collapsed three duplicate b2-vs-local switches.
- `ArtifactService.get` no longer reaches into `repo._load_store()`.
- `SupabaseFileRepository` (REST API + sidecar metadata),
  `SupabaseJobRepository` / `Artifact` / `Prompt` / `PromptExecution`
  (psycopg pool + JSONB + generated indexed columns).
- Schema in
  [supabase/migrations/0001_initial.sql](supabase/migrations/0001_initial.sql);
  applied via [scripts/supabase-migrate.sh](scripts/supabase-migrate.sh)
  (Python entrypoint at [src/scripts/supabase_migrate.py](src/scripts/supabase_migrate.py)).
- Optimistic concurrency on `JobState.version` enforced by
  `SupabaseJobRepository.put(expected_version=…)`.

## 7. Supabase integration debt

Real items that came out of the integration and weren't worth doing
inline. Roughly ordered by severity.

### 7a. `SingleStoreMixin` race condition is still latent on B2

Two workers calling `put_job` (or any `put`) concurrently on the
B2/Local backends both read-modify-write the entire `__store__.json`
blob. Last writer wins; the other write vanishes silently. Postgres
makes the contract concrete via the new `expected_version` parameter,
but B2 ignores it because a single-blob store can't enforce a CAS
atomically. Two paths:

- Switch B2 (and local) to one-object-per-key. The Protocol contract
  doesn't change — only the backend internals.
- Or accept that B2 is single-tenant single-writer forever and document
  it loudly.

### 7b. `GraphJobExecutor` doesn't use `expected_version`

The optimistic-concurrency lane exists end-to-end on Postgres, but the
graph executor still calls `self.repo.put(record)` without passing the
expected version. So the protection is opt-in and unused. Migrate
`mark_running` / `complete_job` / `fail_job` / `update_progress` /
`save_checkpoint` to pass `expected_version=record.state.version - 1`,
and add a retry-or-fail policy when the check fails (e.g. re-read,
re-apply, re-attempt N times).

### 7c. Bucket existence isn't checked at bootstrap

`SupabaseBackend.__init__` builds a `SupabaseFileRepository` but never
verifies the bucket exists. First file upload will 404. Either call
`file_repo.ensure_bucket(public=False)` from the backend constructor,
or add a one-time `bootstrap_supabase` script alongside
`supabase_migrate.py`.

### 7d. Pool / HTTP-client lifecycle on `SupabaseBackend`

`SupabaseBackend._pool` and `SupabaseFileRepository._client` are
created in `__init__` and never closed. Fine for long-running
API/worker processes; leaks for scripts and tests. Add a `close()` on
`SupabaseBackend` and a context-manager flavour, then thread it
through `WorkspaceBootstrap` so entrypoints can shut down cleanly.

### 7e. `tests/integration/` `TRUNCATE`s on module setup ✅ done

`test_supabase_postgres.py` now runs inside a dedicated `test`
schema. `make_pool` / `apply_migrations` both accept a `schema`
kwarg that sets `search_path` via libpq's `options` connection
parameter, so every TRUNCATE / INSERT in the test module is scoped
to `test.*`. `public` is unreachable from these tests by
construction — the gate is gone, and `pytest tests/` is safe against
a populated dev DB. Verified live: ran the suite while the API was
serving `public` data and the API's view didn't budge.

### 7f. `parse_connection_string` workaround for libpq

[src/ai_platform/workspace/storage/structured/supabase.py](src/ai_platform/workspace/storage/structured/supabase.py)
hand-parses the Postgres URL because libpq's URI parser percent-decodes
passwords and chokes on the bytes that come out (Supabase-generated
passwords sometimes contain `%`, `?`, etc.). Harmless workaround; if
the DB password is rotated to something plain-ASCII it becomes a
no-op. Worth keeping until we move to `psycopg.conninfo.conninfo_to_dict`
once libpq tolerates this.

### 7g. Migration runner vs Supabase CLI

`src/scripts/supabase_migrate.py` is a small psycopg runner with its own
`_schema_migrations` table. The SQL is CLI-compatible, but if we ever
adopt `supabase db push` / `supabase db diff` / dashboard migrations,
the bookkeeping has to be reconciled (or our table dropped and the
CLI's `supabase_migrations.schema_migrations` adopted).

### 7h. RLS is off; service-role key bypasses everything

Tables created in `0001_initial.sql` have RLS disabled and the app
authenticates with the service-role-equivalent `sb_secret_*` key.
Single-tenant assumption baked in. When we add user identity, every
query path needs revisiting before turning RLS on, otherwise reads
break in subtle ways.

### 7i. `BACKEND` auto-select doesn't know about Supabase

`make_backend()` defaults to `b2` if `B2_KEY_ID` is set, else `local`.
`supabase` is only chosen when `BACKEND=supabase` is explicit. Either
preserve "user must pick", or extend auto-select to prefer supabase
when `SUPABASE_CONNECTION_STRING` is present.

### 7j. Postgres prompts grow forever

`PromptRegistry.update_instructions` writes a new row per version
(fresh UUID id, bumped `version` field). Postgres has no TTL or
archival; the `prompts` table grows monotonically. Add either a
`current` boolean + `superseded_at` timestamp, or a periodic prune
job.

### 7k. `SupabaseFileRepository` sidecar metadata is two HTTP round-trips

Every `put_canonical_file` now does two POSTs (file + sidecar). Native
Supabase Storage object metadata works for simple cases; if we end up
storing metadata-heavy artifacts we should switch to native metadata
and drop the sidecars. Decision deferred until a real perf signal.

## 7p. Platform/domain split — Phase C (bundle deploy substrate) ⚙️ in progress

The "give the code to my friend" track. Where we are:

- **Phase A** ✅ (PR #3) — domain code lives in per-runtime packages
  (`packages/math-qa/`, `packages/math-conversation/`); platform
  packages are domain-free.
- **Phase A.5** ✅ (PR #4) — platform vocabulary renamed
  (`mathapp-*` → `aiplatform-*`, `mathapp.*` → `ai_platform.*`,
  `mathai.workspace.*` facade deleted).
- **Phase B** ✅ (PR #5) — virgin worker image + chained domain images
  built FROM it via `Dockerfile.worker-domain`. The platform image is
  the same artifact regardless of domain.
- **Phase C, slice 1** ✅ (this PR) — JobDefinition catalog. Bundle
  deploy can now push a JobControl into the platform via
  `POST /job-definitions`; `aiplatform.bundle.deploy_control(...)` is
  the Python entrypoint a domain repo calls. Records are stored
  (Supabase / local / B2) but **routing still goes through the
  in-memory `_job_controls` dict** — the catalog is a parallel
  artifact for now.
- **Phase C, slice 2** 📝 open — cutover. `make_jobs_router` reads the
  discriminated submit/result union from the catalog instead of from
  in-code registration. Workers on boot pull their JobExecution
  references from `runtime_selector` queries against the catalog.
  Composition_root drops from "the source of truth" to "the bootstrap
  seed" (and is eventually retired when wheel upload lands).
- **Phase C, slice 3** 📝 open — ArtifactType catalog. Mirror of the
  JobDefinition shape; lets a tenant register new artifact types
  without baking them into the platform image.
- **Phase C, slice 4** 📝 open — Code package upload. The
  `code_entrypoint` string currently resolves against the in-image
  source tree (Phase B baked the domain wheel in). Slice 4 publishes
  domain wheels independently (GHCR's Python registry or PyPI), and
  the worker pip-installs the wheel at runtime from the
  JobDefinition's `code_entrypoint` package coordinate. After this,
  `Dockerfile.worker-domain` is no longer needed for a tenant — they
  bring the wheel; the platform installs it on the virgin image.
- **Phase D** 📝 open — `aiplatform deploy` CLI + a `bundle.toml`
  manifest. The Python `deploy_control` is the substrate; the CLI is
  the user-facing one-liner ("give your friend the repo, `aiplatform
  deploy` is what they run").

The "PlatformSession" object (the SparkSession-shaped runtime API for
domain code) is its own track — not part of Phase C. Surfaces after
the bundle-deploy + cutover work is done.

## 8. `math_conversation` v1.x follow-ups 📝 open

v1 shipped on `feat/conversation-panel` (multi-persona panel + turn
loop + conclude tool + `source_job_id` hydration; see
[docs/math_conversation.md](docs/math_conversation.md) §What ships in
v1). These are the deliberate v1 deferrals that should land before the
feature graduates.

### 8a. Fill in the five skill bodies

[instructions/math_conversation/skills/*.md](instructions/math_conversation/skills/)
currently ship one-line stub bodies (the loader, tool-allowlist
plumbing, and registry round-trip all work — the *content* is the
todo). An authoring pass per skill: heuristics, 2–3 few-shot examples
from real algebraist / visualist / synthesist moves. Cheap and
high-leverage; the panel quality is bounded by these today.

### 8b. Real-image smoke for crewai's anthropic 0.73 + Claude Sonnet 4.5

`packages/worker[crewai]` resolves `anthropic==0.73.0` (older than the
default runtime's 0.105) because crewai 1.14.6 pins it. Verified
locally that `uv pip compile` resolves cleanly; not yet verified that
`crewai.LLM(model="anthropic/claude-sonnet-4-5-20250929")` actually
talks to the live API through that SDK. Run the smoke entrypoint
(`python -m ai_platform.entrypoints.crewai_smoke "<question>"`) inside the
built `aiplatform-worker-mathconversation` image on first deploy; the test passes
or we fall back to `anthropic` as a direct extras dep.

### 8c. OTLP → Logfire crew traces

The crewai runtime can't load the Logfire SDK (otel-sdk <1.35 pin
clashes with logfire's >=1.39), but `crewai[anthropic]` does ship
`opentelemetry-exporter-otlp` — and Logfire is an OTLP collector. Wire
direct OTLP export from the crewai worker to the same Logfire project
so the panel runs land alongside math_qa traces. Today crew progress
is observable only via the `CrewChatEvent` SSE stream.

### 8d. Per-runtime Celery routing

The single Celery pool today registers all domains (default runtime).
A `math_conversation` job enqueued to celery would hit a worker that
can't run it. Two-pool design: queue per runtime, worker per pool
(EXTRA=default vs EXTRA=crewai). Only matters once we move off the
polling backend in prod.

### 8e. `list_by_type` / `list_by_job` indexed lookups ✅ done

Landed with Perf §9. `ArtifactService.list_by_job(job_id)` is now a
single query on Supabase (JSONB filter on `payload->>'created_by_job'`);
SeedStep just calls it. Same `list_*` family added to the artifacts
router. DB-side functional index left for later (current row count
makes the seq-scan invisible).

### 8g. Per-turn cost surfacing for crewai+anthropic

`ConversationTurn.cost_usd` and `MathConversationArtifact.total_cost_usd`
always show `$0.0000` because `crewai.LLM` + the anthropic SDK doesn't
populate `result.token_usage.total_cost` (crewai's cost computation
ships pricing tables for some providers but not anthropic's modern
Claude models). The API call really happens; the wrapper just can't
read a dollar figure off the response shape.

Two viable fixes:

- Compute cost ourselves from `result.token_usage.{input_tokens,
  output_tokens}` × a hard-coded Claude Sonnet 4.5 price table in
  `workflow.py:RunCrewStep`. Cheap; goes stale if Anthropic changes
  prices.
- Pull it from Anthropic's invoice API. More robust, requires
  additional credentials.

Token counts are already on the response — verified in the smoke
output (`{'input_tokens': 1016, 'output_tokens': 77, ...}`). The
narrow fix is the price-table approach; ~30 LOC including a single
Claude pricing constant.

### 8f. v2 deferrals (not yet planned)

For visibility — items from the design's "does NOT ship in v1" that
have no current ticket: a manager-led / hierarchical CrewAI process
(replaces sequential round-robin once the artifact contract has soak
time), cross-conversation memory, incremental per-turn persistence
(would require a new "streaming artifact" semantic on
`PersistencePolicy`), mid-run human-in-the-loop (`human_input=True` on
tasks). Open these as their own §N when there's a use case.

---

## Frontend (`math-ui/`)

The platform/domain split exists on the backend (`ai_platform.*` vs
domain packages). The frontend is gradually mirroring it. This
section tracks the coherence gaps in [`math-ui/lib/platform/`](math-ui/lib/platform/index.ts)
and the workflow-driven UI. Merged in from the standalone
`math-ui/NEXT_BEST_STEPS.md` on 2026-05-16 when the two repos became
one.

### Frontend §1. `GET /workflows` registry consumed ✅ done

The [/workflows](math-ui/app/workflows/page.tsx) index now fetches
from `GET /workflows`; `WORKFLOW_JOB_TYPES` was removed.
`WorkflowJobType` is a plain `string` — type discipline comes from
"did you fetch this from the backend?" rather than a compile-time
literal.

### Frontend §2. `math-types.ts` split into platform vs domain ✅ done

`math-ui/lib/` now physically separates platform from domain:

- [math-ui/lib/platform/](math-ui/lib/platform/) — job lifecycle
  types ([job-types.ts](math-ui/lib/platform/job-types.ts)), workflow
  types, artifact types, jobs/workflows/artifacts clients,
  active-jobs-store, BFF proxy, hooks, workflow-graph layout. Public
  barrel at [index.ts](math-ui/lib/platform/index.ts).
- [math-ui/lib/domains/math-qa/](math-ui/lib/domains/math-qa/) —
  `MathQAResult` + artifact shapes
  ([types.ts](math-ui/lib/domains/math-qa/types.ts)),
  `mathClient.submitQuestion`
  ([client.ts](math-ui/lib/domains/math-qa/client.ts)), domain
  progress copy
  ([progress-copy.ts](math-ui/lib/domains/math-qa/progress-copy.ts)).

The platform stays domain-agnostic: `JobStatusResponse.result: unknown`
and the math_qa job page narrows at the boundary
(`res.result as MathQAResult | null`). Domain-typed result handling
will be replaced by Frontend §3 (discriminated union) when it lands.

React components stayed in `math-ui/components/{math,artifacts,workflow,...}`
— they're not lib code. A future tidy could move them under
`math-ui/components/domains/math-qa/` and `math-ui/components/platform/`
to match.

### Frontend §3. Make `JobResult` a discriminated union over `job_type` 📝 open

[`JobStatusResponse.result`](math-ui/lib/math-types.ts) is hard-coded
to `MathQAResult | null`. The backend response *is* a discriminated
union (see `result.job_type`), but with a single domain registered the
schema collapses it to a concrete shape.

When a second domain ships, this will break silently in the codegen.
Plan now:

- At the platform level, type `result` as a discriminated union over
  every domain's result variant — generated from the OpenAPI `oneOf` /
  `discriminator`.
- Domain code narrows by `result.job_type` before reading domain
  fields.
- Hooks like [useJobPolling](math-ui/lib/hooks/use-job-polling.ts)
  stay domain-agnostic; they just expose the typed `result` and let
  consumers narrow.

### Frontend §4. Surface `ExecutionPolicy` in `WorkflowSpecResponse` ✅ done

`WorkflowSpecResponse.gates: list[GateSpec]` is now on the wire, with
each entry carrying `{node_name, review_type, params}` derived from
the backend's `ExecutionPolicy`. The
[WorkflowSpecView](math-ui/components/workflow/workflow-spec-view.tsx)
renders a dedicated **Execution policy** section, and the human-wait
detection in
[workflow-graph.ts](math-ui/lib/platform/workflow-graph.ts) now
relies on `stage.is_human_step` (which is policy-derived server-side)
instead of the old `waiting_for` string heuristic.

### Frontend §5. Generic submit form from `submit_params` 📝 open

[QuestionForm](math-ui/components/math/question-form.tsx) is bespoke
math_qa. The same shape is already on the wire as
`WorkflowSpecResponse.submit_params` — the platform should be able to
auto-render a basic submit form (string / number / select inputs) for
any registered job type, with domains optionally overriding via a
registry of custom form components.

This is the natural complement to Frontend §1 (`GET /workflows`
index): once the registry is server-driven, the platform can host
`/workflows/[jobType]/run` as a generic submit page.

### Frontend §6. Platform-level `/jobs` index ✅ done

[/jobs](math-ui/app/jobs/page.tsx) lists every workflow run (history
view). Backend `JobStatusResponse` gained `job_type` and `created_at`
for this use; rows group by status via shadcn `Tabs` (RUNNING /
WAITING_INPUT / SUCCEEDED / FAILED / etc.) with counts, color-coded
status badges, and click-through to domain detail pages
(`/math-qa/[jobId]` for math_qa). Unknown job types stay
informational until a domain registers a route in `JOB_TYPE_ROUTES`.

### Frontend §7a. Artifact viewer ✅ done

Implemented at [/artifacts](math-ui/app/artifacts/page.tsx) +
[/artifacts/[id]](math-ui/app/artifacts/[artifactId]/page.tsx).
Backend artifacts router was migrated from the math domain into
`ai_platform.api.routers.artifacts`; the GET endpoint now returns a
discriminated union over every registered domain's `BaseArtifact`
subclasses (driven by a runtime registry built from each
`Domain.artifact_types`), and the list endpoint returns lightweight
summaries with `job_id` / `artifact_type` / `limit` filters.

### Frontend §7d. Artifact-type registry view ✅ done

[/artifact-types](math-ui/app/artifact-types/page.tsx) reflects every
registered `BaseArtifact` subclass — class name, owning domain, and
the field list derived from its pydantic schema. Backend at
`GET /artifacts/types`. Useful for documenting what each domain
contributes to the platform.

### Frontend §7b. Domain-renderer registry for artifacts 📝 open

[ArtifactCard](math-ui/components/artifacts/artifact-card.tsx)
currently has a hard-coded switch over the three math_qa artifact
types, with a JSON fallback for anything else. Domains should
register their own renderer components keyed by `artifact_type` —
same pattern as the planned generic submit form (Frontend §5). Until
then, every new domain artifact lands in the JSON fallback.

### Frontend §7c. Prompts UI 📝 open

Backend exposes `/prompts`, `/prompts/{name}`, `/prompt-executions`
— no UI yet. Same platform-page pattern as `/workflows` and
`/artifacts`: a list + detail view rendered straight from the
OpenAPI shapes. See
[prompt_registry.md](docs/prompt_registry.md) for the backend
model.

### Perf §9. Artifacts list — fix the N+1 against Supabase ✅ done

`GET /artifacts` was `list_ids() → get(id) per row` — one Supabase
round-trip per artifact, ~5s TTFB on warm cache. Fixed at the service
layer (no schema / index changes):

- `ArtifactRepository` Protocol gained `list_all` / `list_by_type` /
  `list_by_job`, all with optional `limit`. Single-blob backends
  (local, B2) iterate the existing cached `_load_store().items` in
  memory; Supabase runs one SQL per method, with JSONB filters
  (`payload->>'artifact_type'` / `payload->>'created_by_job'`).
- `ArtifactService` exposes typed versions that hydrate to
  `BaseArtifact` subclasses and silently skip unknown discriminators
  (preserves the router's prior resilience contract).
- `GET /artifacts` branches on filter and calls the matching method
  once: no more per-row hydration.
- `SeedStep._load_source_artifacts` (math_conversation, §8e below)
  uses `list_by_job` so seeding from a math_qa job is a single query.

Also folded in: `ArtifactRepository.get_many(ids)` — `_fetch_result`
(both math_qa and math_conversation) used to walk
`get_many([id1, id2, …])` as one-`get`-per-id. Now a single
`SELECT … WHERE artifact_id = ANY(%s)` on Supabase, set-lookup on
single-blob backends. Service preserves the input-order +
fail-loud-on-missing contract via a re-index pass; missing ids
surface in a single `ObjectNotFound` listing them all (was: first
missing id raised, hiding the rest).

Followup if needed at scale: functional indexes on
`(payload->>'artifact_type')` and `(payload->>'created_by_job')` —
trivial migration once row counts make the seq-scan visible.
  - Add `?limit/offset` (and an `artifact_type=` query param) on
    `GET /artifacts` so the panel pulls a page per tab instead of
    everything. Pairs with §10 to halve the React render cost too.

Diagnosed 2026-05-26. Design refined 2026-05-28.

### Perf §10. Artifacts panel — memoize per-card body rendering 📝 open

200 unmemoized `ArtifactCard` instances each call
`katex.renderToString()` / `react-markdown` on every parent render
(~10ms/card → ~2s of sync React work on first paint). `React.memo` the
card, `useMemo` the KaTeX HTML by source string, and `next/dynamic` the
KaTeX import so it leaves the initial JS bundle. Fixes after §9 lands
(fewer cards alone removes most of the pain).

### Tooling §11. Frontend perf playbook 📝 open

Add `docs/frontend_perf_playbook.md` codifying the "is it the API, the
BFF, the React render, or which component?" diagnostic. Modern Selenium
successor (Playwright + Chrome DevTools Protocol) for runtime React
profiling — the curl-based recipe we used today only catches the
API/BFF half. Should include: Playwright tracing for paint timing,
React DevTools Profiler equivalents, and the "count heavy leaf
components × per-instance ms" back-of-envelope.

### Frontend §8. Audit `math-ui/components/workflow/` for hidden math_qa coupling 📝 open

The workflow components were named generically before the platform
split was introduced. Verify
[WorkflowJobRunner](math-ui/components/workflow/workflow-job-runner.tsx),
[WorkflowGraphView](math-ui/components/workflow/workflow-graph-view.tsx),
and
[WorkflowStepperView](math-ui/components/workflow/workflow-stepper-view.tsx)
truly have no domain assumptions, and move them under
`math-ui/components/platform/workflow/` once the directory split
lands.

### Frontend §9. `math_conversation` v1.x FE follow-ups 📝 open

v1 chat surface shipped on `feat/conversation-panel` (lib/domains/
math-conversation, components/conversation, app/math-conversation/*,
math-qa job page CTA — see backend §8 for the matching BE
follow-ups). These are the FE-side deferrals:

- **Promote `ConversationBubble` to `components/library/`** when a
  second domain wants chat-shaped output. Today it lives under
  `components/conversation/` per AGENTS.md ("if a pattern repeats, put
  it in `components/library/`"); v1 has one consumer.
- **Render `ConversationTurn.figure` on turns.** The shape is plumbed
  (turn carries an optional `figure: FigureSpec`) but no panel skill
  produces figures yet; when one does, drop a `<Figure>` from
  `@/components/library` into the bubble.
- **Workflow stepper for the conversation page.** `/math-conversation/[jobId]`
  shows only the chat view; the math_qa page also renders a
  `WorkflowJobRunner` stepper. The panel's three nodes (Seed /
  RunCrew / Finalize) are uninteresting compared to the per-turn
  bubbles, so we skipped it — revisit if users ask "where are we in
  the run?"
- **CrewChatEvent → richer rendering.** `tool_call` / `tool_result`
  events currently fall through to no UI; the `friendly_tool_name`
  map exists in `callbacks.py` for this. Light pass: render a tiny
  "{display} is checking the LaTeX…" line beneath the typing
  indicator. Defer until skill bodies actually exercise tools (BE §8a).
