-- Initial schema for the Supabase backend.
--
-- Each table has a primary-key id and a `payload` (or `spec`/`state`)
-- jsonb column that holds the full Pydantic-serialized record. Indexed
-- columns are GENERATED ALWAYS AS … STORED projections of the JSONB so
-- there's no denormalization drift — write the JSON once, the indexes
-- follow.
--
-- RLS is left disabled on these tables: the app uses the service-role
-- key, single-tenant for now. Flagged as future work in
-- docs/project/supabase_intro.md.

-- ---------------------------------------------------------------------------
-- jobs
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS jobs (
  job_id      uuid PRIMARY KEY,
  spec        jsonb NOT NULL,
  state       jsonb NOT NULL,
  created_at  timestamptz NOT NULL,
  updated_at  timestamptz NOT NULL,
  job_type    text GENERATED ALWAYS AS (spec ->> 'job_type') STORED,
  status      text GENERATED ALWAYS AS (state ->> 'status') STORED,
  version     int  GENERATED ALWAYS AS ((state ->> 'version')::int) STORED
);

CREATE INDEX IF NOT EXISTS jobs_status_idx     ON jobs (status);
CREATE INDEX IF NOT EXISTS jobs_job_type_idx   ON jobs (job_type);
CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs (created_at DESC);

-- ---------------------------------------------------------------------------
-- artifacts
--
-- Single-table-per-workspace, discriminated by `artifact_type`. Splitting
-- into one table per artifact subclass would give stronger column-level
-- typing but require the platform to know each domain's taxonomy — flagged
-- as a layering violation in docs/project/supabase_intro.md and not
-- pursued.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id    text PRIMARY KEY,
  payload        jsonb NOT NULL,
  artifact_type  text GENERATED ALWAYS AS (payload ->> 'artifact_type') STORED,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS artifacts_artifact_type_idx ON artifacts (artifact_type);

-- ---------------------------------------------------------------------------
-- prompts
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS prompts (
  id          text PRIMARY KEY,
  payload     jsonb NOT NULL,
  name        text GENERATED ALWAYS AS (payload ->> 'name') STORED,
  version     text GENERATED ALWAYS AS (payload ->> 'version') STORED,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS prompts_name_idx ON prompts (name);

-- ---------------------------------------------------------------------------
-- prompt_executions
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS prompt_executions (
  id           text PRIMARY KEY,
  payload      jsonb NOT NULL,
  prompt_name  text GENERATED ALWAYS AS (payload ->> 'prompt_name') STORED,
  -- text column rather than timestamptz: the cast (text → timestamptz)
  -- isn't immutable, which Postgres requires for generated columns.
  -- ISO-8601 timestamps sort correctly as text, so the index works as-is.
  executed_at  text GENERATED ALWAYS AS (payload ->> 'executed_at') STORED
);

CREATE INDEX IF NOT EXISTS prompt_executions_prompt_name_idx ON prompt_executions (prompt_name);
CREATE INDEX IF NOT EXISTS prompt_executions_executed_at_idx ON prompt_executions (executed_at DESC);
