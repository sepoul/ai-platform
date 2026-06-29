# Backlog

Open work on the platform, ordered by leverage. Done items get a
short closing note; deep historical context is in git history. Math-
specific backlog is in [`sepoul/math-app`](https://github.com/sepoul/math-app).

Item references: `§N` (this file). Earlier numbering is preserved
for tracking.

---

## Recent landings

- **#68 — Celery: prod (Hetzner) enablement, rehearsed flip + rollback** ✅
  (closes epic #64). The last child: turn `COMPUTE=celery` on prod from a
  doc paragraph into a *rehearsed, reversible* procedure. After #72/#73
  cleared the local compose smoke gate, the operator deployed `main`@d30f4aa
  to `mathapp-prod` (poll first) and rehearsed the flip + rollback on the box
  on 2026-06-29 — **PASS**: default `math_qa` picked up ~1.8 s → SUCCEEDED via
  the broker on both the submit *and* review enqueue paths; crewai
  `math_conversation` ~1.2 s → SUCCEEDED on `runtime.crewai` with the default
  consumer seeing it 0 times (per-runtime isolation); redis up `appendonly
  yes` with no host port (Hetzner FW blocks 6379 too); the #73 install-once
  fix held (no `google/_upb` boot race); rollback clean (`api` back to
  `compute=poll`, poll workers reconnected, no stray containers). This change
  is docs/env-only — no code logic. `docs/operations/hetzner-deploy.md` §6
  flips its status banner from "not yet exercised on the box" to "validated
  2026-06-29" and folds in the exact flip recipe (`COMPUTE=celery` +
  broker/concurrency/reaper vars → `PROFILES="ui celery" redeploy.sh` →
  `stop worker worker-crewai`, with the caveat that a reduced-profile `up`
  leaves the poll workers running) and rollback (`COMPUTE` unset →
  `redeploy.sh` → `rm -fs` the two celery consumers + redis; keep the no-op
  vars). `.prodenv.example` now documents `COMPUTE` / `CELERY_BROKER_URL` /
  `CELERY_CONCURRENCY` (poll stays the prod default); `.env.example` already
  carried all four. **Out of scope** (and not done): defaulting prod to
  celery — this is flip-on-when-we-want-it.

- **#72 — Celery: API can now enqueue from the split api image** ✅ (epic #64).
  In real celery mode on compose, every `math_qa` job hung PENDING and
  `runtime.default` stayed empty: the api container logged
  `ModuleNotFoundError: No module named 'ai_platform.entrypoints.celery_app'`.
  The producer (`CeleryComputeBackend.enqueue`) lazily imported the worker's
  task module — but `celery_app` lives in `packages/worker`, absent from the
  api image (api = api + core) — and #67's `_enqueue_best_effort` then swallowed
  the import error, so the job stranded silently. Two-part fix. (1) *Enqueue by
  name*: the producer builds its own Celery app from `CELERY_BROKER_URL` and
  publishes with `app.send_task("run_job", args=[job_id], queue=…)` — no
  consumer import, so it works with `packages/worker` absent. Per-runtime
  routing (#66) is unchanged (same `celery_queue_for_runtime`); producer +
  consumer resolve `runtime.default` to the identical queue/exchange/routing-key
  (verified by a kombu roundtrip). (2) *Stop hiding producer misconfig*:
  `enqueue` now reports only genuine broker-unavailability (kombu
  `OperationalError` / `ConnectionError`) as the new `EnqueueUnavailable`, which
  `_enqueue_best_effort` still swallows for the reconciler; any *other* error
  (bad `CELERY_BROKER_URL`, routing/import error) propagates and 500s the submit
  — it can never masquerade as a permanent silent PENDING again. Tests:
  send-by-name + worker-module-absent + error-classification in
  `tests/test_celery_routing.py`; producer-misconfig-surfaces +
  broker-unavailable-swallowed in `tests/test_job_runs_router.py`. The committed
  e2e broker test (`tests/integration/test_celery_broker.py`) exercises the real
  `send_task` path. Unblocks #68 (prod flip).

- **#67 — Celery durability: PENDING reconciler + broker-unavailable
  handling** ✅ (epic #64). Under `COMPUTE=poll` the repo *is* the queue, so
  a lost worker self-heals on the next `SELECT`; celery pushes to Redis once,
  so a lost push (broker down at submit, redis restart before an AOF flush,
  or #62's reaper releasing a RUNNING job to PENDING) would sit PENDING
  forever. Restored the net in three parts. (1) *Best-effort submit*: the
  router persists the PENDING `JobRecord` before `enqueue`, then swallows an
  enqueue failure (`_enqueue_best_effort`) — a broker hiccup no longer 500s
  the submit/`/review` and strands the row; the job stays PENDING for the
  reconciler. (2) *Reconciler*: `GraphJobExecutor.reconcile_pending_jobs`
  re-`enqueue`s jobs stuck PENDING past `CELERY_PENDING_RECONCILE_AGE_S`
  (grace window above normal sub-second pickup), scoped to the served job
  types; wired as the `reconcile_jobs` celery-beat task, which also carries
  #62's lease reaper (celery has no poll loop to host it). (3) *Idempotency*:
  `claim_job_for_run` is a PENDING-gated claim — `run_job` uses it instead of
  unconditional `mark_running`, so a re-enqueue that races a live delivery
  no-ops on the second (no double-run). New env
  `CELERY_RECONCILE_INTERVAL_S` / `CELERY_PENDING_RECONCILE_AGE_S` in
  `.env.example`/`.prodenv.example`; `compute-backends.md` celery section
  rewritten (was stale "placeholder"). Tests: `tests/test_pending_reconciler.py`
  + best-effort-submit cases in `tests/test_job_runs_router.py`. The beat
  scheduler itself (`worker -B`) and compose/runtime wiring are sibling
  children (#65/#66/#68); this lands the durability primitives they switch on.

- **#62 — Worker no longer hangs forever on a stale Supabase pooler
  connection** ✅. Two-layer fix. (1) *Fail-fast DB sockets*: `make_pool`
  now also sets `tcp_user_timeout=30s` (bounds an in-flight query on a
  half-open socket — the exact #62 hang, where Supabase rotated its pooler
  IP during an idle window and the next read never returned) and bumps
  `keepalives_count` to 5, completing the #57 hardening. All consumers (api,
  both workers, celery) inherit it through the one central pool factory.
  (2) *Lease reaper*: `JobState.heartbeat_at` is now refreshed at every
  graph step (`update_progress`) and `GraphJobExecutor.reclaim_expired_leases`
  releases a RUNNING job whose worker stopped heartbeating past
  `WORKER_JOB_LEASE_TTL_S` back to PENDING (or FAILED once `max_attempts` is
  used). The poll loop reaps on boot + each idle tick, so a job orphaned by a
  crashed/restarted worker no longer sits RUNNING forever. New env threaded
  through compose + `.env.example`/`.prodenv.example`; diagnose+recover steps
  added to the hetzner-deploy runbook. Optional liveness/healthcheck signal
  (#62 proposed-fix part 3) intentionally deferred. Builds on #57, #48.

- **#56 — Workflow descriptors in the deploy flow** ✅. `/workflows` no
  longer comes up empty after a deploy. New seam mirrors the
  export-manifest split: a pure `build_descriptors_map(controls,
  executions)` (core, intersection of both planes); `gen_workflows`
  gained `--out FILE` (emit descriptors JSON for transport) and
  `--runtime` (scope to one runtime); a **merge-upsert** `POST /workflows`
  (api) accumulates each runtime's contribution into the single blob; and
  `aip workflows list|push` (cli, pure HTTP) drives it. Flow:
  `python -m ai_platform.entrypoints.gen_workflows --runtime <rt> --out
  wf.json` (per runtime) → `aip workflows push --file wf.json`. The
  in-cluster `gen_workflows` (no args, writes the blob directly) still
  works. Follow-up: fold the push into `aip deploy` once per-runtime
  generation is wired into CI/deploy.

- **#49 — Standalone `aiplatform-cli` (`aip`)** ✅ first cut. New
  `packages/cli/` ships a pure-HTTP ops CLI that imports **zero**
  platform internals (guarded by `tests/test_cli_no_platform_imports.py`)
  and installs/versions independently (`pipx install aiplatform-cli`;
  `cli-v*` tag → `pypi-publish-cli.yml`). The introspection that a
  pure-HTTP tool can't do is split out to a domain-side build step,
  `aiplatform export-manifest` (in `aiplatform-core`, `build_manifest`),
  which emits a plain-JSON catalog the CLI replays over HTTP. Commands:
  `login` (profile/config), `deploy`, `job-definitions`, `artifact-types`,
  `jobs`, `cancel` (uses #48's endpoint), `snapshot-openapi`. Builds on
  #45 (control plane now importable off a plain PyPI install). Follow-ups:
  auth wiring once tokens land; consider retiring the in-core deploy CLI
  once `export-manifest` + `aip` cover every path.

- **§7p — Platform/domain split (Phases A–D)** ✅ shipped end-to-end
  through PRs #3–18. Catalogs (JobDefinitions, ArtifactTypes,
  CodePackages), `aiplatform deploy` CLI, `bundle.toml` manifest,
  virgin API + worker images, catalog install on boot, PlatformSession.
- **§7q — Repo split + TS SDK** ✅ shipped through PRs #19–22 +
  the `sepoul/math-app` repo. Catalog-driven control + execution
  discovery (PR #19), `@sepoul-packages/sdk` consumed by both UIs
  (PRs #20 + #21), math packages and math-ui extracted to math-app,
  synthetic `_demo` baseline (PR #22).
- **PR-1 — Media ingestion + blob-backed artifacts** ✅
  ([`platform-requirements.md`](platform-requirements.md), P0 keystone).
  `POST /media` (multipart) lands user bytes in the storage plane via a
  new `MediaService` over `FileRepository` (`media/` prefix) and returns
  a `storage_ref`; `GET /media/download?ref=` streams them back.
  `BaseArtifact` gained `storage_ref` / `content_type` / `byte_size`
  (persisted) plus a transient `storage_url` hydrated to the download URL
  on `GET /artifacts/{id}` (excluded from `ArtifactService.put`). The
  `_demo` echo job threads an optional `storage_ref` input → state →
  artifact so the full ingest loop is UAT-able out of the box (also
  fixed a latent `UUID(uuid)` crash in the demo's persist). Bytes
  traverse the control plane on ingest only — no compute/LLM/artifact
  generation runs there. ASR/OCR/vision stay domain `[execution]` deps.

See [`docs/architecture.md`](docs/architecture.md) for the resulting
shape and [`docs/guides/deploy-a-domain.md`](docs/guides/deploy-a-domain.md)
for how a domain plugs in now.

---

## Open

### §1l — Docstring rollout

Every public module has a top-of-file docstring; many `__init__`s
still don't. Surface in mkdocstrings via the autogenerated reference
once `gen_ref_pages.py` is restored against `packages/*/src/`.

### §1m — `deploy_prompts.py --update`

The current deploy script only writes prompts that don't yet exist.
Add a `--update` flag that overwrites by id, and a `--dry-run` that
prints the diff. Keep idempotent.

### §1n — mkdocs strict mode + `repo_url`

`mkdocs build --strict` currently fails on broken links inside the
reference tree (and on the dropped math docs). Fix the dangling
refs, then turn on strict mode in CI. Also set `repo_url` so each
page has an "Edit on GitHub" link.

### §2 — Honor `idempotency_key` on submission

`POST /jobs/runs/submit` currently mints a new job per request even
when the same `idempotency_key` is presented. Make it look up
existing rows by key first and return the existing record's id.
Spec: 24-hour window, key scoped per `job_type`.

### §3 — Storage tests for `SingleStoreMixin`

The local + B2 repositories share `SingleStoreMixin`; their behavior
is tested through the higher-level Job / Artifact / etc. repository
tests, not directly. Add focused tests for the mixin (load-on-miss,
write-through, last-modified semantics).

### §4 — Move `src/scripts/` into `ai_platform.scripts`

Top-level `scripts/*.sh` are bash entry points; the Python equivalents
(prompt deploy, openapi dump, etc.) live under `src/scripts/`. After
the repo split, `src/` no longer exists. Promote these into
`ai_platform.scripts` so they're importable via `python -m`.

### §5 — Centralize `_utc_now`

Half a dozen places do `datetime.now(timezone.utc)`. Move it into a
single `ai_platform.utilities.time` helper so future test-time-control
(freezegun, mocking) lives in one place.

### §7 — Supabase integration debt

The migration script (`scripts.supabase_migrate`) runs from inside
the API container; that means a deploy that ships a new migration
needs a separate `docker compose exec` step. Either:

- Have the API process apply migrations idempotently at boot, OR
- Move migrations into the deploy script.

Also: the prompt registry's Supabase path doesn't yet use the
generic `SingleStoreMixin` shape; it has its own RLS-aware logic.
Worth converging.

### §7r — Drop `composition_root._DOMAINS` to `[]`

After §7q Phase 3, `_DOMAINS` is the cold-boot fallback and contains
only `_demo`. The platform can come up with an empty list as long as
the catalog discovery succeeds. Drop `_DOMAINS` to `[]` once we trust
the catalog-driven path enough; the synthetic `_demo` package then
deploys via `aiplatform deploy` like any other domain, including in
local dev (compose's bootstrap script needs to learn this).

### §8 — Catalog-driven *live* routing

Today `make_jobs_router` builds the discriminated submit/result union
from the in-memory `_job_controls` dict populated at boot. So a
freshly-POSTed JobDefinition isn't live until the API restarts. Add
an SSE / watch endpoint on `/job-definitions` that pushes catalog
changes, and have the API recompute its routing union on the fly.

### §9 — `JobDefinition.code_package_ref`

Foreign key into `code_packages` so the worker verifies that the
entrypoint resolves to *this* deployed package, not whatever was
lying around. Tightens what's currently a loose string contract.

### §PR — Domain → platform asks (PR-2 … PR-7)

From [`platform-requirements.md`](platform-requirements.md) (the
math-app domain's ask list). PR-1 shipped (see Recent landings). Open,
in priority order:

- **PR-2 — cross-domain shared types + read facade** (P0): sanction a
  shared library tier for artifact types more than one domain
  produces/consumes, plus a thin read facade (`get` / `list_by_type`)
  so a domain reads another's artifacts by ref/type without importing
  its package. Types + reads only; write-ownership stays with the
  producer.
- **PR-3 — structured artifact query** (P1): add a metadata/tag field
  to `BaseArtifact` + a filtered `GET /artifacts?type=&tag=&created_after=&created_by=&limit=`.
  Structured filtering only — vector/semantic search stays domain-side
  (design §13).
- **PR-5 — cross-run thread / journey grouping** (P1): domain-modeled
  first (a `LearningJourneyArtifact` referencing run-ids + concept-ids,
  zero platform change); promote to a first-class `Session`/`Thread`
  only if multiple features converge on needing it.
- **PR-4 — scheduled / triggered runs** (P2): external cron →
  `POST /jobs/runs/submit` first; promote to a stored
  `(job_type, input_template, cron)` primitive only once a second
  domain wants it.
- **PR-7 — per-run model / budget tier** (P2): a `model_tier` / `effort`
  knob on the job input or `ExecutionPolicy`, threaded to `deps_factory`
  so a domain picks model + iteration cap from one place.
- **Live conversation room** (feature 5): explicitly *not* a platform
  item — a separate realtime service that uses the platform only as an
  artifact sink (reuses PR-1's ingest).

### §SDK — contract-first SDK + auto-regen

From [`sdk-contract-first-plan.md`](sdk-contract-first-plan.md). Core
loop **landed** (PRs #26 + #27): `aiplatform declare-artifacts`
(contract-first; register artifact types with no wheel/job),
`aiplatform snapshot-openapi` (dump the full OpenAPI where you're already
on the tailnet), and the `sdk-regen` workflow (commit the snapshot →
CI regenerates `schema.d.ts` → PR; CI never joins the tailnet, no
secrets). The remaining moves are **deferred — promote when a real need
appears** (the box snapshot already yields a complete OpenAPI and the
sibling `file:` consumers already work):

- **GitHub Packages publish** (move 3): only when a *non-sibling*
  consumer (a friend's repo) needs the SDK. Note: GitHub Packages scopes
  to the org, so this means publishing as `@sepoul/sdk` and having
  consumers alias it (`"@sepoul-packages/sdk": "npm:@sepoul/sdk@^x"`) so their
  imports don't change — a coordinated change across this repo + math-ui.
- **`GET /sdk/openapi.json` assembler** (move 4): assemble the full
  OpenAPI from the catalog's stored `json_schema` rows (with `$defs`
  hoisting/namespacing) so a snapshot can be produced *without* a
  fully-booted instance. Only needed if generating off a domain-less
  API matters.
- **Auto-fire on deploy** (move 5): largely obviated — the manual
  `snapshot-openapi` + commit *is* the trigger, and that's the chosen
  workflow.

---

## Conventions

- One numbered section per item.
- `✅ done` / `📝 open` / `⚙️ in progress` markers.
- When you finish an item, leave a one-line note in the section about
  what landed and where; deep history goes in commit messages and PR
  bodies, not here.
