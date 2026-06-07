# Storage backends

Three backends; one contract. The platform asks for "a job repo, an
artifact repo, a prompt repo, a prompt-execution repo, and a file
repo" and the active backend hands them over. Selected at startup by
the `BACKEND` env var:

| `BACKEND` | Structured records | Blob files |
|---|---|---|
| `local` (default in dev) | one JSON blob per entity, on disk | filesystem, sidecar metadata |
| `b2` | one JSON blob per entity, in a B2 bucket | B2 object storage, native metadata |
| `supabase` | Postgres tables, JSONB payloads, generated indexed columns | Supabase Storage, sidecar metadata |

Wiring lives in
[`workspace/storage/backends.py`](../src/ai_platform/workspace/storage/backends.py).
Adding a fourth backend is one class plus one branch in
`make_backend()`; everything downstream — `PlatformClient`,
`bootstrap_workspace`, the FastAPI routers, the graph executor — talks
to the row-shaped Protocols, not concrete classes.

---

## The contract

[`workspace/storage/protocols.py`](../src/ai_platform/workspace/storage/protocols.py)
defines four Protocols, one per domain entity:

- `JobRepository`: `put(record, *, expected_version=None)`, `get(job_id)`,
  `list(*, status, job_type, limit)`, `delete(job_id)`.
- `ArtifactRepository`: `put(artifact_id, payload_dict)`,
  `get(artifact_id) -> dict`, `list_ids()`. Hydration into typed
  `BaseArtifact` subclasses lives in `ArtifactService`, *outside* the
  repository, so backends stay domain-agnostic.
- `PromptRepository`: `put(prompt)`, `get(prompt_id)`, `list()`.
- `PromptExecutionRepository`: `put(execution)`, `list(limit=None)`.

Plus the existing `FileRepository` for blob bytes
([`workspace/storage/blobs/base.py`](../src/ai_platform/workspace/storage/blobs/base.py)).

The contract is row-shaped. The local + B2 backends *implement* it
with a single JSON blob per entity (`__store__.json`) read-modified-
written on every put — that's a private impl detail of those
backends. Callers never see it. The Supabase backend implements it
with one row per record — same contract, different substrate.

Anything that needs to know about storage depends on the Protocol,
never on `LocalJobRepository` / `B2JobRepository` / etc.

---

## Why this unlocks something real

> Before this initiative, "storage" was a pile of reach-in workarounds.
> `ArtifactService.get` was doing `repo._load_store()` to bypass a typing
> bug; `list_jobs(status=…)` was loading every job into memory and
> filtering in Python; `JobState.version` had been on the model since
> day one and nothing enforced it. Each one was a paper cut. Together
> they were the shape of a platform that couldn't grow up.

The unlock isn't "we added a third backend." It's that the contract
finally stopped lying.

**Real queries become real.** `list_jobs(status="RUNNING", job_type="math_qa", limit=100)`
on Postgres is now a `WHERE status='RUNNING' AND job_type='math_qa' ORDER BY created_at DESC LIMIT 100`
backed by indexes — instead of "load all jobs into memory, filter in
Python, hope the dataset stays small." Local + B2 still do the
in-memory thing because their substrate can't help, but the API surface
no longer pretends those are equivalent operations.

**Generated columns mean no schema/JSON drift.** Indexed fields like
`status`, `job_type`, `artifact_type`, `version` are
`GENERATED ALWAYS AS (jsonb_col ->> 'field') STORED`. The JSON is
written once; the column is a projection of it. There's no
denormalization step in application code, no trigger to maintain, no
risk of the index disagreeing with the truth. Adding a new indexed
field is one line of DDL.

**Optimistic concurrency is now a thing.** `JobState.version` was
dead weight on the local + B2 backends — there was no atomic way to
enforce it. On Postgres,
`put(record, expected_version=N)` runs an `UPDATE … WHERE job_id=$1
AND version=N` and raises `OptimisticConcurrencyError` if the row has
moved on. The graph executor isn't using it yet (tracked under §7b in
[NEXT_BEST_STEPS](../NEXT_BEST_STEPS.md)) but the safety lane is
plumbed end-to-end. The local + B2 backends accept the kwarg and
ignore it — the Protocol is honest about what they can and can't do.

**RLS is one configuration switch away.** Tables ship with RLS
disabled and the app uses the service-role-equivalent `sb_secret_*`
key. When the product needs multi-tenancy, RLS goes on and queries get
filtered by `auth.uid()` at the database — without rewriting the
application. The seam is in the right place.

**Free tier for prototyping; one provider for blobs and rows.**
Supabase's free tier (500 MB Postgres, 1 GB Storage) is plenty for
dev. Both blob and structured storage live behind one project, one
secret, one billing surface. We didn't get rid of B2 — it stays
selectable for production weight — but the development loop now
matches a production-shaped database instead of "JSON files on disk."

The contract cleanup also paid off backwards. Local and B2 don't
benefit from indexed `WHERE` clauses, but they *do* benefit from a
service layer that no longer reaches past the repository's front door.
`ArtifactService.get` is one line again. `GraphJobExecutor` depends on
a Protocol, not a concrete class. New domain entities don't have to
re-derive the storage shape — they implement the four Protocols and
they're done.

---

## Configuration

All three backends read from `.env` (see [`.env.example`](../.env.example)).

### Local

```bash
BACKEND=local
LOCAL_DATA_DIR=./mathdata    # any writable directory
```

Default for dev. `mathdata/` is gitignored.

### B2 (Backblaze)

```bash
BACKEND=b2
B2_KEY_ID=...
B2_APP_KEY=...
B2_BUCKET=app-data
```

The bucket must exist; we don't auto-create.

### Supabase

```bash
BACKEND=supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...      # server-only, RLS-bypassing
SUPABASE_BUCKET=app-data               # auto-created on first use
SUPABASE_CONNECTION_STRING=postgresql://postgres.<ref>:<password>@<region>.pooler.supabase.com:5432/postgres
```

`SUPABASE_SECRET_KEY` is the modern format that replaced the legacy
JWT-format `service_role` key. **Server-only — never expose it to the
frontend, never put it in any `NEXT_PUBLIC_*` variable.**

`SUPABASE_CONNECTION_STRING` is the session pooler URI from the
dashboard (Settings → Database → Session pooler, port 5432). It's
hand-parsed in
[`structured/supabase.py`](../src/ai_platform/workspace/storage/structured/supabase.py)
because libpq's URI parser percent-decodes passwords and chokes on
some Supabase-generated bytes.

#### One-time setup

```bash
# Apply migrations against the configured DB (idempotent).
./scripts/supabase-migrate.sh
```

The runner reads `supabase/migrations/*.sql` in lexical order and
records what's applied in `_schema_migrations`. The SQL is also
Supabase-CLI-compatible if we ever switch to `supabase db push`.

The bucket is auto-created the first time a `SupabaseFileRepository`
runs `ensure_bucket()` — currently called only from the integration
test fixture. If the API runs first, the upload will 404 until the
bucket exists; tracked under §7c in
[NEXT_BEST_STEPS](../NEXT_BEST_STEPS.md).

---

## Migrating between backends

Because every backend implements the same Protocols, copying data
between them is just "`list` on the source, `put` on the target." That
mechanism lives in [`src/scripts/migrate_backend.py`](../src/scripts/migrate_backend.py)
and the wrapper [`scripts/migrate-backend.sh`](../scripts/migrate-backend.sh).

```bash
# Inspect first; counts only, no writes.
./scripts/migrate-backend.sh --source local --target supabase --dry-run

# Real copy. Idempotent — re-runs UPSERT; counts on the target don't double.
./scripts/migrate-backend.sh --source local --target supabase

# Subset.
./scripts/migrate-backend.sh --source supabase --target local --what jobs,artifacts
```

It moves: jobs, artifacts, prompts, prompt_executions, and files at
the root level of the file repository. It does *not* walk file
subdirectories (the `FileRepository.list_canonical_files` contract
takes a single `dir_path`) and it does *not* touch domain-specific
stores outside the four Protocols (e.g. the legacy
`mathdata/math_qa/__store__.json` from before the artifact router was
promoted to the platform).

Unit coverage in
[`tests/test_migrate_backend.py`](../tests/test_migrate_backend.py)
runs the mechanism between two `LocalBackend`s pointed at separate
temp dirs — no network. Live cross-backend round-trips run as part of
`tests/integration/`.

---

## Schema (Supabase)

In [`supabase/migrations/0001_initial.sql`](../supabase/migrations/0001_initial.sql).
Each table has a primary-key id, a JSONB payload (or `spec`/`state`
split for jobs), and indexed columns generated from the JSON:

```sql
CREATE TABLE jobs (
  job_id      uuid PRIMARY KEY,
  spec        jsonb NOT NULL,
  state       jsonb NOT NULL,
  created_at  timestamptz NOT NULL,
  updated_at  timestamptz NOT NULL,
  job_type    text GENERATED ALWAYS AS (spec  ->> 'job_type') STORED,
  status      text GENERATED ALWAYS AS (state ->> 'status')   STORED,
  version     int  GENERATED ALWAYS AS ((state ->> 'version')::int) STORED
);
```

Same shape for `artifacts`, `prompts`, `prompt_executions`. The lone
quirk is `prompt_executions.executed_at` — stored as `text` rather
than `timestamptz` because the cast isn't immutable, which Postgres
requires for generated columns. ISO-8601 timestamps sort correctly as
text, so the descending index works as-is.

Tables per artifact type — splitting the single `artifacts` table
into one table per `BaseArtifact` subclass — is *not* what we do.
Stronger column-level typing would mean the platform has to know
every domain's artifact taxonomy, which is the kind of layering
violation [`AGENTS.md`](../AGENTS.md) tells you to refuse. Single
table, JSONB payload, discriminated by `artifact_type` is the soul of
the model and we're keeping it.

---

## Outstanding debt

The integration shipped honest about what it doesn't yet do. See
[NEXT_BEST_STEPS §7](../NEXT_BEST_STEPS.md) for the full list — the
load-bearing items are §7a (B2 single-blob race condition still
latent), §7b (graph executor doesn't pass `expected_version` yet),
and §7c (bucket-existence check at bootstrap).
