"""Public, row-shaped repository contracts.

These Protocols are the source of truth for the storage layer.
Backends (local, B2, Supabase) implement them however their substrate
prefers — one JSON blob, one row per record, an S3 object, whatever.
That choice is private to the backend and must not leak through this
surface.

In particular, the `SingleStoreMixin` / `_JobStoreMixin` /
`_ArtifactStoreMixin` machinery used by the local and B2 backends
today is an implementation detail. Callers depend on the Protocol,
not on the existence of an underlying store.

Steps 2+ of the Supabase initiative (see
`docs/project/supabase_intro.md`) migrate concrete repos and callers
to these contracts; this file is the no-impact first step.
"""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ai_platform.ai.prompts.models import Prompt, PromptExecution
from ai_platform.workspace.storage.structured.job_repository import (
    JobRecord,
    JobStatus,
)


class JobRepository(Protocol):
    def put(self, record: JobRecord, *, expected_version: int | None = None) -> JobRecord:
        """Persist `record`. When `expected_version` is set, the write
        is conditional: the row currently in storage must have that
        version, otherwise raise `OptimisticConcurrencyError`. Backends
        whose substrate can't enforce the check (single-blob stores)
        are allowed to ignore the parameter.
        """
        ...

    def get(self, job_id: UUID | str) -> JobRecord: ...

    def list(
        self,
        *,
        status: JobStatus | None = None,
        job_type: str | None = None,
        limit: int | None = None,
    ) -> list[JobRecord]: ...

    def delete(self, job_id: UUID | str) -> None: ...


class ArtifactRepository(Protocol):
    """Artifacts are stored as raw payload dicts.

    Hydration into typed `BaseArtifact` subclasses is the service
    layer's responsibility (see `ArtifactService`), not the
    repository's — that keeps backends domain-agnostic.
    """

    def put(self, artifact_id: str, payload: dict) -> None: ...

    def get(self, artifact_id: str) -> dict: ...

    def list_ids(self) -> list[str]: ...


class PromptRepository(Protocol):
    def put(self, prompt: Prompt) -> Prompt: ...

    def get(self, prompt_id: str) -> Prompt: ...

    def list(self) -> list[Prompt]: ...


class PromptExecutionRepository(Protocol):
    def put(self, execution: PromptExecution) -> PromptExecution: ...

    def list(self, *, limit: int | None = None) -> list[PromptExecution]: ...
