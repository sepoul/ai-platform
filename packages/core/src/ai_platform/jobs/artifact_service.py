"""Workspace-side artifact API.

Wraps a generic ArtifactRepository and uses a registry mapping
`artifact_type` strings to concrete `BaseArtifact` subclasses to hydrate
stored payloads back into typed artifacts.
"""
from __future__ import annotations

from typing import Iterable
from uuid import UUID

from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.workspace.storage.protocols import ArtifactRepository


ArtifactRegistry = dict[str, type[BaseArtifact]]


class ArtifactService:
    """Put / get / list artifacts in the workspace's artifact repo.

    Hydration uses the `registry` (artifact_type -> class) supplied at
    construction. Domains add their concrete artifact types to this
    registry when wiring the workspace client.
    """

    def __init__(
        self,
        repo: ArtifactRepository,
        registry: ArtifactRegistry,
    ) -> None:
        self.repo = repo
        self.registry = dict(registry)

    def register(self, artifact_cls: type[BaseArtifact]) -> None:
        artifact_type = artifact_cls.model_fields["artifact_type"].default
        if artifact_type is None:
            raise ValueError(
                f"{artifact_cls.__name__} must declare an `artifact_type` Literal default"
            )
        self.registry[artifact_type] = artifact_cls

    def put(self, artifact: BaseArtifact) -> UUID:
        self.repo.put(
            str(artifact.artifact_id),
            artifact.model_dump(mode="json"),
        )
        return artifact.artifact_id

    def get(self, artifact_id: UUID | str) -> BaseArtifact:
        return self._hydrate(self.repo.get(str(artifact_id)))

    def get_many(self, ids: Iterable[UUID | str]) -> list[BaseArtifact]:
        return [self.get(i) for i in ids]

    def _hydrate(self, raw: dict) -> BaseArtifact:
        artifact_type = raw.get("artifact_type")
        cls = self.registry.get(artifact_type)
        if cls is None:
            raise ValueError(f"No registered class for artifact_type={artifact_type!r}")
        return cls.model_validate(raw)
