-- CodePackage catalog — installable code blobs that back a
-- JobDefinition's `code_entrypoint`.
--
-- The bytes (a .whl) live in the file repository (Supabase Storage,
-- B2, or local fs depending on backend). This table carries the
-- pointer + metadata: which runtime should install it, the original
-- filename, sha256 integrity hash, and size.
--
-- Worker install (a follow-up slice) reads from this table on boot,
-- downloads the referenced blob, verifies sha256, and `pip install`s
-- it before resolving the JobDefinition's `code_entrypoint`. Today
-- the table is recorded only — no consumer yet — so a misshapen row
-- can't break the running platform.

CREATE TABLE IF NOT EXISTS code_packages (
  id                text        PRIMARY KEY,
  name              text        NOT NULL,
  version           text        NOT NULL,
  runtime_selector  text        NOT NULL,
  filename          text        NOT NULL,
  blob_id           text        NOT NULL,
  sha256            text        NOT NULL,
  size_bytes        bigint      NOT NULL,
  payload           jsonb       NOT NULL,
  deployed_at       timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT code_packages_name_version_key UNIQUE (name, version)
);

-- Worker boot reads all packages for its runtime in one query.
CREATE INDEX IF NOT EXISTS idx_code_packages_runtime_selector
    ON code_packages (runtime_selector);

-- "Latest by name" lookup.
CREATE INDEX IF NOT EXISTS idx_code_packages_name_deployed_at
    ON code_packages (name, deployed_at DESC);
