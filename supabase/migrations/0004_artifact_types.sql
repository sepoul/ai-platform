-- ArtifactType catalog — the persisted shadow of a BaseArtifact subclass.
--
-- Mirror of the JobDefinition table: one row per (name, version), where
-- `name` is the artifact_type discriminator string (e.g. "math_question",
-- "math_conversation"). The platform records every artifact class a
-- domain registers; future code-package upload (Phase C slice 4) lets a
-- friend's domain add new classes without rebuilding the worker.
--
-- Today the row is recorded by `register_control_domains` as a parallel
-- artifact of bootstrap and powers `GET /artifact-types`. Hydration
-- still uses the in-memory `ArtifactService` registry; the cutover
-- lands with wheel install.

CREATE TABLE IF NOT EXISTS artifact_types (
  id           text        PRIMARY KEY,
  name         text        NOT NULL,
  version      text        NOT NULL,
  domain       text        NOT NULL,
  class_name   text        NOT NULL,
  payload      jsonb       NOT NULL,
  deployed_at  timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT artifact_types_name_version_key UNIQUE (name, version)
);

-- "Types for this domain" lookup, used by the bundle CLI to diff a
-- deploy against what the platform already has registered.
CREATE INDEX IF NOT EXISTS idx_artifact_types_domain
    ON artifact_types (domain);

-- "Latest by name" lookup, for SDK consumers asking "what's the schema
-- of math_question?" without a version.
CREATE INDEX IF NOT EXISTS idx_artifact_types_name_deployed_at
    ON artifact_types (name, deployed_at DESC);
