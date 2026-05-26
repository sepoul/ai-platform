"""Supabase Postgres implementations of the structured-record repositories.

Each table holds a primary-key id and a `jsonb` payload column with the
full Pydantic-serialized record; indexed columns (`status`, `job_type`,
`artifact_type`, …) are GENERATED projections of the JSON. See
`supabase/migrations/0001_initial.sql` for the schema.

Connections are pooled via psycopg's `ConnectionPool`. RLS is off; the
service-role key (or in our case `sb_secret_*` via the standard
Postgres user) is what the connection string authenticates as.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional, TYPE_CHECKING
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from ai_platform.ai.prompts.models import Prompt, PromptExecution
from ai_platform.workspace.storage.exceptions import (
    ObjectNotFound,
    OptimisticConcurrencyError,
)
from ai_platform.workspace.storage.structured.job_repository import (
    JobRecord,
    JobSpec,
    JobState,
    JobStatus,
)


def parse_connection_string(url: str) -> dict:
    """Parse `postgresql://user:password@host:port/dbname` into the
    keyword form psycopg accepts.

    Treats the password as opaque (no URL-decoding) — Supabase-generated
    passwords sometimes contain `%`, `?`, and other URL-meaningful
    characters. libpq's URI parser tries to percent-decode them and
    chokes; the keyword form sidesteps that entirely.
    """
    if not url.startswith(("postgresql://", "postgres://")):
        raise ValueError(f"Not a Postgres URL: {url[:20]}…")
    rest = url.split("://", 1)[1]
    userinfo, sep, hostpart = rest.rpartition("@")
    if not sep:
        raise ValueError("Connection string missing '@'")
    user, _, password = userinfo.partition(":")
    hostport, _, dbname = hostpart.partition("/")
    dbname = dbname.split("?", 1)[0]
    host, _, port = hostport.partition(":")
    return {
        "host": host,
        "port": int(port) if port else 5432,
        "user": user,
        "password": password,
        "dbname": dbname or "postgres",
    }


def make_pool(
    connection_string: str,
    *,
    min_size: int = 1,
    max_size: int = 4,
    schema: str | None = None,
) -> ConnectionPool:
    """Open a connection pool. Caller owns the lifetime.

    When `schema` is given, every connection in the pool runs
    `SET search_path = <schema>` on checkout, so all queries are
    scoped to that schema. Used by integration tests to isolate
    destructive operations from `public`.
    """
    params = parse_connection_string(connection_string)
    parts = [f"{k}={v}" for k, v in params.items()]
    if schema:
        # libpq per-connection options; runs at connect time and persists
        # for the connection lifetime. Spaces in option values are
        # backslash-escaped in conninfo strings.
        parts.append(rf"options=-c\ search_path={schema}")
    kwargs = " ".join(parts)
    return ConnectionPool(kwargs, min_size=min_size, max_size=max_size, open=True)


# ---------------------------------------------------------------------------
# Migrations — extracted so both the CLI script and the integration-test
# fixture can apply them. Schema-aware: writes the tables to whichever
# schema is supplied (default `public`).
# ---------------------------------------------------------------------------

from ai_platform.utilities.paths import find_ancestor_containing

_MIGRATIONS_DIR = find_ancestor_containing("supabase") / "supabase" / "migrations"

_TRACKING_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS _schema_migrations (
    name        text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
"""


def apply_migrations(connection_string: str, *, schema: str | None = None) -> int:
    """Apply pending SQL migrations from `supabase/migrations/*.sql`.

    Idempotent. Returns the number of migrations newly applied.
    When `schema` is given, the schema is created (`IF NOT EXISTS`)
    and all DDL runs inside it via `search_path`.
    """
    params = parse_connection_string(connection_string)
    extra: dict[str, Any] = {}
    if schema:
        # libpq per-connection options; runs at connect time.
        extra["options"] = f"-c search_path={schema}"

    files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        return 0

    with psycopg.connect(**params, **extra) as conn:
        if schema:
            with conn.transaction():
                conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                # Re-set search_path after schema create (transaction
                # boundary can reset connection state under some pgbouncer
                # modes; cheap insurance).
                conn.execute(f'SET search_path TO "{schema}"')
        with conn.transaction():
            conn.execute(_TRACKING_TABLE_DDL)
        applied = {
            r[0]
            for r in conn.execute("SELECT name FROM _schema_migrations").fetchall()
        }
        pending = [f for f in files if f.name not in applied]
        for f in pending:
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO _schema_migrations (name) VALUES (%s)", (f.name,)
                )
        return len(pending)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class SupabaseJobRepository:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def put(self, record: JobRecord, *, expected_version: int | None = None) -> JobRecord:
        params = (
            str(record.spec.job_id),
            Jsonb(json.loads(record.spec.model_dump_json())),
            Jsonb(json.loads(record.state.model_dump_json())),
            record.created_at,
            record.updated_at,
        )
        if expected_version is None:
            with self._pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO jobs (job_id, spec, state, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (job_id) DO UPDATE SET
                        spec       = EXCLUDED.spec,
                        state      = EXCLUDED.state,
                        updated_at = EXCLUDED.updated_at
                    """,
                    params,
                )
            return record

        # Conditional update: row must currently be at expected_version.
        with self._pool.connection() as conn:
            cur = conn.execute(
                """
                UPDATE jobs SET
                    spec       = %s,
                    state      = %s,
                    updated_at = %s
                WHERE job_id = %s AND version = %s
                """,
                (params[1], params[2], params[4], params[0], expected_version),
            )
            if cur.rowcount == 0:
                # Either the row doesn't exist or its version drifted.
                raise OptimisticConcurrencyError(
                    f"Job {record.spec.job_id} not at version {expected_version}"
                )
        return record

    def get(self, job_id: str | UUID) -> JobRecord:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT spec, state, created_at, updated_at FROM jobs WHERE job_id = %s",
                (str(job_id),),
            ).fetchone()
        if row is None:
            raise ObjectNotFound(f"Job not found: {job_id}")
        return self._row_to_record(row)

    def list(
        self,
        *,
        status: JobStatus | None = None,
        job_type: str | None = None,
        limit: int | None = None,
    ) -> List[JobRecord]:
        sql = "SELECT spec, state, created_at, updated_at FROM jobs WHERE TRUE"
        params: list[Any] = []
        if status is not None:
            sql += " AND status = %s"
            params.append(status.value)
        if job_type is not None:
            sql += " AND job_type = %s"
            params.append(job_type)
        sql += " ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_record(r) for r in rows]

    def delete(self, job_id: str | UUID) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM jobs WHERE job_id = %s", (str(job_id),))

    @staticmethod
    def _row_to_record(row) -> JobRecord:
        spec, state, created_at, updated_at = row
        return JobRecord(
            spec=JobSpec.model_validate(spec),
            state=JobState.model_validate(state),
            created_at=created_at,
            updated_at=updated_at,
        )


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

class SupabaseArtifactRepository:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def put(self, artifact_id: str, payload: dict) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (artifact_id, payload)
                VALUES (%s, %s)
                ON CONFLICT (artifact_id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (artifact_id, Jsonb(payload)),
            )

    def get(self, artifact_id: str) -> dict:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT payload FROM artifacts WHERE artifact_id = %s",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise ObjectNotFound(f"Artifact not found: {artifact_id}")
        return row[0]

    def list_ids(self) -> list[str]:
        with self._pool.connection() as conn:
            rows = conn.execute("SELECT artifact_id FROM artifacts ORDER BY created_at DESC").fetchall()
        return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

class SupabasePromptRepository:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def put(self, prompt: Prompt) -> Prompt:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO prompts (id, payload)
                VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (prompt.id, Jsonb(json.loads(prompt.model_dump_json()))),
            )
        return prompt

    def get(self, prompt_id: str) -> Prompt:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT payload FROM prompts WHERE id = %s",
                (prompt_id,),
            ).fetchone()
        if row is None:
            raise ObjectNotFound(f"Prompt not found: {prompt_id}")
        return Prompt.model_validate(row[0])

    def list(self) -> list[Prompt]:
        with self._pool.connection() as conn:
            rows = conn.execute("SELECT payload FROM prompts").fetchall()
        return [Prompt.model_validate(r[0]) for r in rows]


# ---------------------------------------------------------------------------
# Prompt executions
# ---------------------------------------------------------------------------

class SupabasePromptExecutionRepository:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def put(self, execution: PromptExecution) -> PromptExecution:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO prompt_executions (id, payload)
                VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (execution.id, Jsonb(json.loads(execution.model_dump_json()))),
            )
        return execution

    def list(self, *, limit: int | None = None) -> list[PromptExecution]:
        sql = "SELECT payload FROM prompt_executions ORDER BY executed_at DESC"
        params: list[Any] = []
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [PromptExecution.model_validate(r[0]) for r in rows]
