"""Live round-trip tests for the four Supabase Postgres repositories.

Runs against the `test` schema, not `public`. Every TRUNCATE and
INSERT here is scoped via `search_path` to `test.*`, so production
data in `public` is untouchable from this module. Schema is created
on demand and migrations applied idempotently on fixture setup.

Skipped unless `SUPABASE_CONNECTION_STRING` is set.
"""
from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv

from ai_platform.ai.prompts.models import Prompt, PromptExecution
from ai_platform.workspace.storage.exceptions import (
    ObjectNotFound,
    OptimisticConcurrencyError,
)
from ai_platform.workspace.storage.structured.job_repository import (
    JobRecord,
    JobStatus,
)
from ai_platform.workspace.storage.structured.supabase import (
    SupabaseArtifactRepository,
    SupabaseJobRepository,
    SupabasePromptExecutionRepository,
    SupabasePromptRepository,
    apply_migrations,
    make_pool,
)

load_dotenv()

if not os.getenv("SUPABASE_CONNECTION_STRING"):
    pytest.skip("SUPABASE_CONNECTION_STRING not set", allow_module_level=True)

TEST_SCHEMA = "test"


@pytest.fixture(scope="module")
def pool():
    conn_str = os.environ["SUPABASE_CONNECTION_STRING"]
    # Create the test schema (idempotent) and run migrations inside it.
    apply_migrations(conn_str, schema=TEST_SCHEMA)
    p = make_pool(conn_str, schema=TEST_SCHEMA)
    # TRUNCATE is now scoped to test.* via search_path — public is untouched.
    with p.connection() as conn:
        conn.execute("TRUNCATE jobs, artifacts, prompts, prompt_executions")
    yield p
    p.close()


# --- Jobs -----------------------------------------------------------------


def test_jobs_put_get_list_delete(pool):
    repo = SupabaseJobRepository(pool)
    a = JobRecord.create(job_type="alpha", graph_ref="g")
    b = JobRecord.create(job_type="beta",  graph_ref="g")
    repo.put(a)
    repo.put(b)

    fetched = repo.get(a.spec.job_id)
    assert fetched.spec.job_type == "alpha"
    assert fetched.state.status == JobStatus.PENDING

    all_jobs = repo.list()
    assert {r.spec.job_type for r in all_jobs} == {"alpha", "beta"}

    only_alpha = repo.list(job_type="alpha")
    assert [r.spec.job_type for r in only_alpha] == ["alpha"]

    a.mark_running()
    repo.put(a)
    running = repo.list(status=JobStatus.RUNNING)
    assert [r.spec.job_id for r in running] == [a.spec.job_id]

    repo.delete(a.spec.job_id)
    with pytest.raises(ObjectNotFound):
        repo.get(a.spec.job_id)


def test_jobs_optimistic_concurrency(pool):
    repo = SupabaseJobRepository(pool)
    record = JobRecord.create(job_type="cc", graph_ref="g")
    repo.put(record)
    assert record.state.version == 0

    # Reader A loads at version 0; bumps to 1; commits with expected=0. OK.
    record.mark_running()
    assert record.state.version == 1
    repo.put(record, expected_version=0)

    # Stale write: caller still thinks the row is at 0, but it's now at 1.
    stale = repo.get(record.spec.job_id)  # actual version=1
    stale.mark_running()                  # bumps to 2 in memory
    with pytest.raises(OptimisticConcurrencyError):
        repo.put(stale, expected_version=0)  # wrong expected — should fail

    # Correct expected_version on a fresh read still works.
    fresh = repo.get(record.spec.job_id)
    prev = fresh.state.version
    fresh.update_progress(stage="x")
    repo.put(fresh, expected_version=prev)


# --- Artifacts ------------------------------------------------------------


def test_artifacts_put_get_list(pool):
    repo = SupabaseArtifactRepository(pool)
    aid = uuid.uuid4().hex
    repo.put(aid, {"artifact_type": "ghost", "artifact_id": aid, "label": "spooky"})

    got = repo.get(aid)
    assert got["label"] == "spooky"

    assert aid in repo.list_ids()

    with pytest.raises(ObjectNotFound):
        repo.get("does-not-exist")


# --- Prompts --------------------------------------------------------------


def test_prompts_put_get_list(pool):
    repo = SupabasePromptRepository(pool)
    p = Prompt(
        name="concept.test",
        domain="concept",
        description="t",
        instructions="say hi",
    )
    repo.put(p)
    fetched = repo.get(p.id)
    assert fetched.instructions == "say hi"

    listed = repo.list()
    assert any(x.id == p.id for x in listed)


# --- Prompt executions ----------------------------------------------------


def test_prompt_executions_put_list_orders_by_executed_at_desc(pool):
    repo = SupabasePromptExecutionRepository(pool)
    e1 = PromptExecution(prompt_name="x", prompt_version="0.1.0")
    e2 = PromptExecution(prompt_name="x", prompt_version="0.1.1")
    repo.put(e1)
    repo.put(e2)

    listed = repo.list(limit=2)
    # newest first; e2 was created after e1
    assert listed[0].id == e2.id
    assert listed[1].id == e1.id
