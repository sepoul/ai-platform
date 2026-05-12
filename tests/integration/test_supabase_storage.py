"""Live round-trip test for SupabaseFileRepository.

Skipped unless `SUPABASE_URL` and `SUPABASE_SECRET_KEY` are set.
Hits the real Supabase Storage API; uses a uniquely-prefixed test
namespace per run so it's safe to repeat.
"""
from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv

from ai_platform.workspace.storage.blobs.base import PutFilePayload
from ai_platform.workspace.storage.blobs.supabase import (
    SupabaseFileRepository,
    SupabaseFileRepositoryConfig,
)

load_dotenv()

if not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SECRET_KEY")):
    pytest.skip("SUPABASE_URL / SUPABASE_SECRET_KEY not set", allow_module_level=True)


@pytest.fixture(scope="module")
def repo() -> SupabaseFileRepository:
    cfg = SupabaseFileRepositoryConfig(
        url=os.environ["SUPABASE_URL"],
        secret_key=os.environ["SUPABASE_SECRET_KEY"],
        bucket_name=os.getenv("SUPABASE_BUCKET", "app-data"),
        # Unique per test run so concurrent / repeated runs don't collide.
        prefix=f"tests/{uuid.uuid4().hex[:8]}",
    )
    r = SupabaseFileRepository(cfg)
    r.ensure_bucket(public=False)
    return r


def test_put_get_roundtrip(repo: SupabaseFileRepository):
    payload = PutFilePayload(
        logical_name="hello.txt",
        bytes_data=b"hello supabase",
        content_type="text/plain",
        metadata={"source": "smoke-test"},
    )
    ref = repo.put_canonical_file(payload)
    assert ref.logical_name == "hello.txt"
    assert ref.content_type == "text/plain"

    assert repo.get_canonical_file_bytes("hello.txt") == b"hello supabase"
    assert repo.get_canonoical_file_metadata("hello.txt") == {"source": "smoke-test"}


def test_get_missing_raises(repo: SupabaseFileRepository):
    from ai_platform.workspace.storage.exceptions import ObjectNotFound

    with pytest.raises(ObjectNotFound):
        repo.get_canonical_file_bytes("does-not-exist.txt")


def test_list_filters_sidecars_and_metadata(repo: SupabaseFileRepository):
    repo.put_canonical_file(PutFilePayload(
        logical_name="a.txt", bytes_data=b"a", content_type="text/plain",
        metadata={"kind": "alpha"},
    ))
    repo.put_canonical_file(PutFilePayload(
        logical_name="b.txt", bytes_data=b"b", content_type="text/plain",
        metadata={"kind": "beta"},
    ))

    listed = repo.list_canonical_files("")
    names = set(listed.keys())
    assert "a.txt" in names and "b.txt" in names
    assert not any(n.endswith(".__meta__.json") for n in names)

    only_alpha = repo.list_canonical_files("", metadata={"kind": "alpha"})
    assert set(only_alpha.keys()) == {"a.txt"}
