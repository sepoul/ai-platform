"""JobDefinitionService — thin orchestration over the catalog.

The repository deals in raw `JobDefinitionRecord`s; this service is
where the API and the bundle helper land their domain concerns:
deriving an `id` from `(name, version)`, validating that
`runtime_selector` is one the platform knows about, etc. Single class
to keep call sites simple.
"""
from __future__ import annotations

from typing import Literal

from ai_platform.workspace.storage.protocols import JobDefinitionRepository
from ai_platform.workspace.storage.structured.job_definition_repository import (
    JobDefinitionRecord,
)

# Known runtimes today. Kept in lockstep with `ai_platform.jobs.runtimes.RUNTIMES`;
# enforced at deploy time so a bogus selector can't sneak into the catalog.
KNOWN_RUNTIMES: tuple[str, ...] = ("default", "crewai")


class JobDefinitionService:
    def __init__(self, repo: JobDefinitionRepository):
        self.repo = repo

    # ---- Writes ----

    def deploy(self, record: JobDefinitionRecord) -> JobDefinitionRecord:
        """Idempotent upsert keyed on `(name, version)` → `id`.

        Re-deploying the same `(name, version)` replaces the payload
        and bumps `deployed_at`. The first version of bundle deploy
        does NOT mint a new version on every push; callers should
        bump the version explicitly when the schema changes.
        """
        if record.runtime_selector not in KNOWN_RUNTIMES:
            raise ValueError(
                f"Unknown runtime_selector {record.runtime_selector!r}; "
                f"expected one of {KNOWN_RUNTIMES}"
            )
        expected_id = JobDefinitionRecord.make_id(record.name, record.version)
        if record.id != expected_id:
            raise ValueError(
                f"record.id={record.id!r} doesn't match name@version "
                f"({expected_id!r}); deploy must not pre-compute a divergent id"
            )
        return self.repo.put(record)

    # ---- Reads ----

    def get(self, definition_id: str) -> JobDefinitionRecord:
        return self.repo.get(definition_id)

    def get_by_name(self, name: str) -> JobDefinitionRecord:
        """Latest-deployed version of `name`."""
        return self.repo.get_by_name(name)

    def list(self, *, runtime_selector: str | None = None) -> list[JobDefinitionRecord]:
        return self.repo.list(runtime_selector=runtime_selector)
