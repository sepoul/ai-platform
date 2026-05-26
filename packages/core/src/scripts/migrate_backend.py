"""Copy every entity from one storage backend to another.

The Repository Protocols (`JobRepository`, `ArtifactRepository`,
`PromptRepository`, `PromptExecutionRepository`, `FileRepository`) are
identical across backends, so a backend-to-backend migration is just
"`list` on the source, `put` on the target" — no per-backend special
casing. The target's `put` is an UPSERT on Supabase Postgres and an
overwrite-by-key on local + B2, so re-runs are safe.

Run via the bash wrapper (handles `.env` + `PYTHONPATH=src`):

    ./scripts/migrate-backend.sh --source local --target supabase
    ./scripts/migrate-backend.sh --source local --target supabase --dry-run
    ./scripts/migrate-backend.sh --source supabase --target local --what jobs,artifacts

What gets migrated:

- jobs, artifacts, prompts, prompt_executions — the four
  Protocol-shaped entity stores.
- files at the root level of the file repository. Subdirectories are
  not walked (the `FileRepository.list_canonical_files` contract takes
  a single `dir_path` and doesn't recurse).

What does NOT get migrated:

- Domain-specific stores outside the four Protocols (e.g. legacy
  `mathdata/math_qa/__store__.json` from before the artifact router
  was promoted to the platform). Those are domain concerns.
"""
from __future__ import annotations

import argparse
import sys
from typing import Iterable

from dotenv import load_dotenv

from ai_platform.workspace.storage.backends import Backend, make_backend
from ai_platform.workspace.storage.blobs.base import PutFilePayload

load_dotenv()

ENTITIES = ("jobs", "artifacts", "prompts", "prompt_executions", "files")


# ---------------------------------------------------------------------------
# Per-entity migrators. Each returns (read, wrote) counts.
# ---------------------------------------------------------------------------

def _migrate_jobs(source: Backend, target: Backend, dry_run: bool) -> tuple[int, int]:
    records = source.job_repo.list()
    if dry_run:
        return len(records), 0
    for r in records:
        target.job_repo.put(r)
    return len(records), len(records)


def _migrate_artifacts(source: Backend, target: Backend, dry_run: bool) -> tuple[int, int]:
    ids = source.artifact_repo.list_ids()
    if dry_run:
        return len(ids), 0
    for aid in ids:
        target.artifact_repo.put(aid, source.artifact_repo.get(aid))
    return len(ids), len(ids)


def _migrate_prompts(source: Backend, target: Backend, dry_run: bool) -> tuple[int, int]:
    prompts = source.prompt_repo.list()
    if dry_run:
        return len(prompts), 0
    for p in prompts:
        target.prompt_repo.put(p)
    return len(prompts), len(prompts)


def _migrate_prompt_executions(source: Backend, target: Backend, dry_run: bool) -> tuple[int, int]:
    execs = source.prompt_execution_repo.list()
    if dry_run:
        return len(execs), 0
    for e in execs:
        target.prompt_execution_repo.put(e)
    return len(execs), len(execs)


def _migrate_files(source: Backend, target: Backend, dry_run: bool) -> tuple[int, int]:
    refs = source.file_repo.list_canonical_files("")
    if not refs:
        return 0, 0
    if dry_run:
        return len(refs), 0
    wrote = 0
    for logical, ref in refs.items():
        body = source.file_repo.get_canonical_file_bytes(logical)
        try:
            meta = source.file_repo.get_canonoical_file_metadata(logical)
        except Exception:
            meta = {}
        target.file_repo.put_canonical_file(PutFilePayload(
            logical_name=logical,
            bytes_data=body,
            content_type=ref.content_type,
            metadata=meta,
        ))
        wrote += 1
    return len(refs), wrote


_MIGRATORS = {
    "jobs": _migrate_jobs,
    "artifacts": _migrate_artifacts,
    "prompts": _migrate_prompts,
    "prompt_executions": _migrate_prompt_executions,
    "files": _migrate_files,
}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def migrate(
    source: Backend,
    target: Backend,
    *,
    what: Iterable[str] = ENTITIES,
    dry_run: bool = False,
) -> dict[str, tuple[int, int]]:
    """Copy each requested entity type from source to target.

    Returns a {entity: (read, wrote)} map. `wrote == 0` with `read > 0`
    indicates `--dry-run`.
    """
    results: dict[str, tuple[int, int]] = {}
    for entity in what:
        migrator = _MIGRATORS[entity]
        results[entity] = migrator(source, target, dry_run)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, choices=("local", "b2", "supabase"))
    parser.add_argument("--target", required=True, choices=("local", "b2", "supabase"))
    parser.add_argument(
        "--source-root",
        help="LOCAL_DATA_DIR for the source (only when --source=local).",
    )
    parser.add_argument(
        "--target-root",
        help="LOCAL_DATA_DIR for the target (only when --target=local).",
    )
    parser.add_argument(
        "--what",
        default=",".join(ENTITIES),
        help=f"Comma-separated entities to copy. Default: all ({','.join(ENTITIES)}).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count only; don't write.")
    args = parser.parse_args()

    if args.source == args.target and args.source_root == args.target_root:
        print(f"Refusing to migrate {args.source} → itself with identical roots.")
        return 2

    what = [w.strip() for w in args.what.split(",") if w.strip()]
    unknown = set(what) - set(ENTITIES)
    if unknown:
        print(f"Unknown entity types: {sorted(unknown)}. Valid: {ENTITIES}")
        return 2

    source = make_backend(args.source, root_dir=args.source_root)
    target = make_backend(args.target, root_dir=args.target_root)

    print(f"[migrate-backend] {source.name} → {target.name}"
          f"{' (dry-run)' if args.dry_run else ''}")
    print(f"[migrate-backend] entities: {', '.join(what)}")

    results = migrate(source, target, what=what, dry_run=args.dry_run)

    print()
    print(f"{'entity':<20} {'read':>8} {'wrote':>8}")
    print("-" * 38)
    for entity, (read, wrote) in results.items():
        print(f"{entity:<20} {read:>8} {wrote:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
