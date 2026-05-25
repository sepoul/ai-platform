"""Math workspace artifact API.

Thin facade over the platform's `ArtifactService` and the file repo. The
workspace exposes one generic surface (put/get/list artifacts by ID);
domain-specific lookups happen at the API layer.
"""
from __future__ import annotations

from typing import Iterable
from uuid import UUID

from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.workspace.storage.blobs.base import FileRepository, PutFilePayload


class MathArtifactService:
    def __init__(
        self,
        artifact_store: ArtifactService,
        file_repo: FileRepository,
    ):
        self.artifact_store = artifact_store
        self.file_repo = file_repo

    # -------- Artifacts --------

    def put_artifact(self, artifact: BaseArtifact) -> UUID:
        return self.artifact_store.put(artifact)

    def get_artifact(self, artifact_id: UUID | str) -> BaseArtifact:
        return self.artifact_store.get(artifact_id)

    def get_artifacts(self, ids: Iterable[UUID | str]) -> list[BaseArtifact]:
        return self.artifact_store.get_many(ids)

    def list_artifact_ids(self) -> list[str]:
        return self.artifact_store.repo.list_ids()

    # -------- Generic file storage --------

    def upload_file(
        self,
        *,
        logical_name: str,
        bytes_data: bytes,
        content_type: str | None = None,
        metadata: dict | None = None,
    ):
        return self.file_repo.put_canonical_file(
            PutFilePayload(
                logical_name=logical_name,
                bytes_data=bytes_data,
                content_type=content_type,
                metadata=metadata or {},
            )
        )

    def download_file(self, logical_name: str) -> bytes:
        return self.file_repo.get_canonical_file_bytes(logical_name)
