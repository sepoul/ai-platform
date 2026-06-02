"""ArtifactTypeService — thin orchestration over the catalog.

Mirror of [[job_definition_service]]: derives `id` from `(name, version)`,
performs idempotent upsert via the underlying repository, exposes
list/get helpers. Validation here is intentionally minimal — an artifact
type is a free-form discriminator name, not gated to a closed set
(unlike `runtime_selector`).
"""
from __future__ import annotations

from ai_platform.workspace.storage.protocols import ArtifactTypeRepository
from ai_platform.workspace.storage.structured.artifact_type_repository import (
    ArtifactTypeRecord,
)


class ArtifactTypeService:
    def __init__(self, repo: ArtifactTypeRepository):
        self.repo = repo

    def deploy(self, record: ArtifactTypeRecord) -> ArtifactTypeRecord:
        """Idempotent upsert keyed on `(name, version)` → `id`."""
        if not record.name:
            raise ValueError("ArtifactType.name must be non-empty")
        if not record.domain:
            raise ValueError("ArtifactType.domain must be non-empty")
        expected_id = ArtifactTypeRecord.make_id(record.name, record.version)
        if record.id != expected_id:
            raise ValueError(
                f"record.id={record.id!r} doesn't match name@version "
                f"({expected_id!r}); deploy must not pre-compute a divergent id"
            )
        return self.repo.put(record)

    def get(self, type_id: str) -> ArtifactTypeRecord:
        return self.repo.get(type_id)

    def get_by_name(self, name: str) -> ArtifactTypeRecord:
        return self.repo.get_by_name(name)

    def list(self, *, domain: str | None = None) -> list[ArtifactTypeRecord]:
        return self.repo.list(domain=domain)
