# Supabase backend — initiative plan

Status: ✅ all six stages landed on branch `supabase-backend`.
Outstanding work tracked under §7 of
[NEXT_BEST_STEPS.md](../../NEXT_BEST_STEPS.md).

## Goal

Add Supabase as a third storage backend (Postgres for structured
records, Supabase Storage for blobs) alongside the existing `local`
and `b2` backends. Use the work as the forcing function to fix a
layering issue that today lets the storage implementation pattern
leak into service layers.

The two backends stay siblings selectable via `BACKEND=`. B2 may
eventually retire — keeping it for now.

## The architectural call (decided)

**The repository contract is row-shaped and lives in the platform.
The "single store JSON blob" pattern (today's `SingleStoreMixin` /
`_JobStoreMixin` / `_ArtifactStoreMixin`) is a private implementation
detail of the local + B2 backends — it must not leak through the
public surface.**

Concretely this means:

- Each domain entity (jobs, artifacts, prompts, prompt_executions)
  has a single Protocol defining `get` / `list` / `put` / `delete`
  semantics.
- `ArtifactService.get` no longer reaches into `repo._load_store()`
  to work around `StoredRecord[T]` typing — that workaround
  disappears once `ArtifactRepository.get(id)` returns the typed
  payload directly.
- Local + B2 keep using a single `__store__.json` blob behind the
  Protocol if they want. The Supabase Postgres backend uses one row
  per record. Callers cannot tell the difference.

The guiding principle: the truth lives in the repository contract,
not in any one backend's implementation detail. Local and B2 don't
need to push their store pattern through the public surface — that's
their private concern. This is the contract.

## Decisions made

| Question | Decision |
|---|---|
| Stage 2 path | Path B — row-shaped contract with one Protocol per domain entity |
| Postgres driver | `psycopg` (sync, direct via the Supabase pooler URL) |
| Migrations | Supabase CLI SQL files in `supabase/migrations/` (no Alembic) |
| Backend co-existence | Keep B2 alongside Supabase, selectable via `BACKEND=` |
| Auth / RLS | Off for now: service-role key, single-tenant. Flagged as future work |
| Hydration of `BaseArtifact` | Stays in `ArtifactService`, *outside* the repository contract — keeps backends domain-agnostic |

## Issues flagged (carry forward)

1. **`SingleStoreMixin` race condition is already a latent bug on
   B2.** Two workers calling `put_job` concurrently both
   read-modify-write the whole store; the second write clobbers the
   first. Postgres surfaces it; B2 hides it. Out of scope for the
   first cut — fix on the B2 side later (e.g. one-object-per-job).
2. **`JobState.version` is unused.** Optimistic concurrency lane
   exists in the model but no backend enforces it. Supabase
   implementation should — track in step 6.
3. **`PlatformClient` is hardwired to B2.** `default_client` and
   `make_b2_repo` predate the second backend. Step 3 collapses this.
4. **Service-role key handling.** `SUPABASE_SERVICE_ROLE_KEY`
   bypasses RLS — must stay server-side, never reach the frontend.
5. **Free-tier limits.** Supabase free is 500 MB Postgres + 1 GB
   Storage; project pauses after ~1 week of inactivity. Fine for
   dev; will bite under sustained batch load.

## Plan (staged)

### Step 1 — Define the four Repository Protocols ✅ done

New file: `src/ai_platform/workspace/storage/protocols.py`. No
backend changes, no caller changes. Protocols are the row-shaped
contract every backend implements going forward.

Surface (from grepping today's actual usage):

- `JobRepository`: `put`, `get`, `list(status, job_type, limit)`,
  `delete`
- `ArtifactRepository`: `put(artifact_id, payload_dict)`,
  `get(artifact_id) -> dict`, `list_ids`
- `PromptRepository`: `put`, `get`, `list`
- `PromptExecutionRepository`: `put`, `list(limit)`

### Step 2 — Migrate Local + B2 concrete repos behind the Protocols ✅ done

- Concrete classes implement the Protocol surface. The mixin
  internals (`_load_store`, `SingleStoreMixin`) become file-private
  helpers used only inside `b2.py` / `local.py` modules.
- Update callers (`graph_execution.py`, `api/routers/*`,
  `PromptRegistry`, `ArtifactService`, `compute/celery.py`) to use
  the Protocol surface.
- **Drop `ArtifactService.get`'s `_load_store` leak** as part of
  this step — falls out for free.
- Tests: existing test suite must stay green.

### Step 3 — Consolidate `PlatformClient` + `bootstrap_workspace` ✅ done

- One `Backend.create(name)` factory returning all four repos.
- One config object per backend; collapse the parallel
  `Local*Config` / `B2*Config` Pydantic classes.
- `bootstrap_workspace` no longer imports backend-specific classes.
- Adding a third backend stops being three-place edit.

### Step 4 — Supabase Storage as a `FileRepository` ✅ done

- Smallest unit. Validates env vars, free-tier behavior, S3-compat
  client choice.
- Doesn't touch the structured side. Independent of steps 1–3.
- Env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, bucket name.

### Step 5 — Supabase Postgres for jobs/artifacts/prompts ✅ done

- Tables: `jobs`, `artifacts`, `prompts`, `prompt_executions`.
- Schema lives in `supabase/migrations/*.sql`, applied via
  `supabase db push`.
- `psycopg` connection pool, configured once in the backend factory.
- `put` becomes `INSERT … ON CONFLICT (id) DO UPDATE`.
- `list_jobs(status=…, job_type=…, limit=…)` becomes a real
  `WHERE` query — first time these filters mean anything.
- RLS off (service-role key); flagged for future.

### Step 6 — Optimistic concurrency on `JobState.version` ✅ done (Supabase enforces; B2/local accept the kwarg as a no-op, see §7a/§7b in NEXT_BEST_STEPS)

- Supabase: `UPDATE … WHERE job_id = $1 AND version = $2`. Raise on
  zero rows affected.
- B2: same idea, plus the underlying single-blob race fix
  (one-object-per-job).
- Contract addition: `put(record, expected_version: int | None = None)`.

## Out of scope (for this initiative)

- RLS / Auth integration. Single-tenant service-role until product
  needs multi-tenancy.
- Frontend changes. The OpenAPI surface doesn't move.
- B2 retirement. Keep it functional; revisit once Supabase has
  burned in.
- **Tables per artifact type.** Supabase will store artifacts in a
  single `artifacts` table with a `payload jsonb` column,
  discriminated by `artifact_type`. Splitting into one table per
  artifact subclass would give stronger column-level typing in
  Postgres but would require the platform to know about every
  domain's artifact taxonomy — a layering violation flagged in
  `AGENTS.md`. Flagged for future thought; not pursued now.

## Reference

- Branch: `supabase-backend`
- Driver: `psycopg[binary,pool]`
- Migration tool: Supabase CLI (`supabase db push`)
- See [`AGENTS.md`](../../AGENTS.md) for repo-wide conventions.
