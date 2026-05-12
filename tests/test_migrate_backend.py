"""Unit tests for the backend-to-backend migration mechanism.

Uses two LocalBackend instances pointed at separate temp dirs — same
Protocol surface as Supabase, no network. Live local ↔ supabase
round-trips live under tests/integration/.
"""
from __future__ import annotations

from pathlib import Path

from ai_platform.ai.prompts.models import Prompt, PromptExecution
from ai_platform.workspace.storage.backends import LocalBackend
from ai_platform.workspace.storage.blobs.base import PutFilePayload
from ai_platform.workspace.storage.structured.job_repository import (
    JobRecord,
)
from scripts.migrate_backend import migrate


def _seed_source(b: LocalBackend) -> None:
    b.job_repo.put(JobRecord.create(job_type="alpha", graph_ref="g"))
    b.job_repo.put(JobRecord.create(job_type="beta", graph_ref="g"))
    b.artifact_repo.put("art-1", {"artifact_type": "ghost", "artifact_id": "art-1", "label": "x"})
    b.artifact_repo.put("art-2", {"artifact_type": "ghost", "artifact_id": "art-2", "label": "y"})
    b.prompt_repo.put(Prompt(name="p", domain="d", description="x", instructions="hi"))
    b.prompt_execution_repo.put(PromptExecution(prompt_name="p", prompt_version="0.1.0"))
    b.file_repo.put_canonical_file(PutFilePayload(
        logical_name="hello.txt",
        bytes_data=b"hi",
        content_type="text/plain",
        metadata={"k": "v"},
    ))


def test_migrate_copies_every_entity(tmp_path: Path):
    source = LocalBackend(root_dir=str(tmp_path / "src"))
    target = LocalBackend(root_dir=str(tmp_path / "dst"))
    _seed_source(source)

    results = migrate(source, target)

    assert results == {
        "jobs": (2, 2),
        "artifacts": (2, 2),
        "prompts": (1, 1),
        "prompt_executions": (1, 1),
        "files": (1, 1),
    }

    # Target now mirrors source.
    assert {r.spec.job_type for r in target.job_repo.list()} == {"alpha", "beta"}
    assert set(target.artifact_repo.list_ids()) == {"art-1", "art-2"}
    assert target.artifact_repo.get("art-1")["label"] == "x"
    assert [p.name for p in target.prompt_repo.list()] == ["p"]
    assert len(target.prompt_execution_repo.list()) == 1
    assert target.file_repo.get_canonical_file_bytes("hello.txt") == b"hi"
    assert target.file_repo.get_canonoical_file_metadata("hello.txt") == {"k": "v"}


def test_migrate_dry_run_reads_but_doesnt_write(tmp_path: Path):
    source = LocalBackend(root_dir=str(tmp_path / "src"))
    target = LocalBackend(root_dir=str(tmp_path / "dst"))
    _seed_source(source)

    results = migrate(source, target, dry_run=True)

    # Read counts are real; write counts are zero.
    assert all(wrote == 0 for (_, wrote) in results.values())
    assert results["jobs"][0] == 2

    # Target stays empty.
    assert target.job_repo.list() == []
    assert target.artifact_repo.list_ids() == []
    assert target.prompt_repo.list() == []


def test_migrate_is_idempotent(tmp_path: Path):
    source = LocalBackend(root_dir=str(tmp_path / "src"))
    target = LocalBackend(root_dir=str(tmp_path / "dst"))
    _seed_source(source)

    migrate(source, target)
    migrate(source, target)  # second pass

    # Target counts unchanged (puts are UPSERT/overwrite-by-key).
    assert len(target.job_repo.list()) == 2
    assert len(target.artifact_repo.list_ids()) == 2
    assert len(target.prompt_repo.list()) == 1


def test_migrate_subset(tmp_path: Path):
    source = LocalBackend(root_dir=str(tmp_path / "src"))
    target = LocalBackend(root_dir=str(tmp_path / "dst"))
    _seed_source(source)

    migrate(source, target, what=["jobs", "artifacts"])

    assert len(target.job_repo.list()) == 2
    assert len(target.artifact_repo.list_ids()) == 2
    # Not migrated.
    assert target.prompt_repo.list() == []
    assert target.prompt_execution_repo.list() == []
