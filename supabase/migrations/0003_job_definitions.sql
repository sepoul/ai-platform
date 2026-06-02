-- JobDefinition catalog — the persisted shadow of a JobControl.
--
-- Domains register at deploy time via POST /job-definitions; one row
-- per (name, version). The platform API uses these rows to know what
-- jobs exist + their schemas; the worker uses runtime_selector to
-- decide which subset of definitions it serves. Both consumers land
-- in subsequent PRs — this migration is the substrate.
--
-- Schema design follows the existing tables: a primary-key id (the
-- "{name}@{version}" composite), a JSONB payload for the full record,
-- and surface columns for the fields any query is going to filter on
-- (name, version, runtime_selector). `payload` carries label,
-- input_schema, result_schema, gates, output_artifact_type_refs.

CREATE TABLE IF NOT EXISTS job_definitions (
  id                text        PRIMARY KEY,
  name              text        NOT NULL,
  version           text        NOT NULL,
  runtime_selector  text        NOT NULL,
  code_entrypoint   text        NOT NULL,
  payload           jsonb       NOT NULL,
  deployed_at       timestamptz NOT NULL DEFAULT now(),

  -- Idempotency on re-deploy: POST with the same (name, version)
  -- targets the same row (also enforced by `id = "{name}@{version}"`).
  CONSTRAINT job_definitions_name_version_key UNIQUE (name, version)
);

-- Worker boot reads all definitions for its runtime in one query.
CREATE INDEX IF NOT EXISTS idx_job_definitions_runtime_selector
    ON job_definitions (runtime_selector);

-- "Latest by name" lookup. Used by both the API (routing post-cutover
-- by name without a version) and the bundle-deploy CLI (to know
-- whether a deploy is creating or updating).
CREATE INDEX IF NOT EXISTS idx_job_definitions_name_deployed_at
    ON job_definitions (name, deployed_at DESC);
