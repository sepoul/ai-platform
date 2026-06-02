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
from ai_platform.workspace.storage.structured.artifact_type_repository import (
    ArtifactTypeRecord,
)
from ai_platform.workspace.storage.structured.code_package_repository import (
    CodePackageRecord,
)
from ai_platform.workspace.storage.structured.job_definition_repository import (
    JobDefinitionRecord,
)
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

    The three `list_*` shapes all return raw payload dicts so the
    repository never has to know about `BaseArtifact` subclasses.
    Backends that can push filters into storage (Supabase: JSONB
    expressions on `payload->>'artifact_type'` / `created_by_job`)
    should do so; single-blob backends (local, B2) filter in memory
    over the one cached store blob. The hot path is `GET /artifacts`
    and `SeedStep._load_source_artifacts` — both used to walk
    `list_ids()` and call `get()` per artifact (one round-trip each).
    """

    def put(self, artifact_id: str, payload: dict) -> None: ...

    def get(self, artifact_id: str) -> dict: ...

    def get_many(self, artifact_ids: list[str]) -> list[dict]:
        """Batch-fetch by id. One round-trip on Supabase
        (`WHERE artifact_id = ANY(%s)`); set-lookup on single-blob
        backends. Order of the returned list is NOT guaranteed to
        match the input — `ArtifactService.get_many` indexes by id
        and re-orders, and is the contract callers should depend on.
        Missing ids are silently dropped at this layer; the service
        layer compares counts and raises `ObjectNotFound` to preserve
        the previous fail-loud semantics.
        """
        ...

    def list_ids(self) -> list[str]:
        """Return every artifact id. Cheap on single-blob backends;
        kept for legacy callers (tests, migrate_backend). Prefer
        `list_all` / `list_by_type` / `list_by_job` in router and
        service code — those return payloads in one round-trip.
        """
        ...

    def list_all(self, *, limit: int | None = None) -> list[dict]:
        """All artifact payloads, newest-first. Single query on
        Supabase; one blob read on local / B2. `limit` lets callers
        bound DB load on large stores.
        """
        ...

    def list_by_type(self, artifact_type: str, *, limit: int | None = None) -> list[dict]:
        """Payloads whose `artifact_type` discriminator matches."""
        ...

    def list_by_job(self, job_id: str, *, limit: int | None = None) -> list[dict]:
        """Payloads whose `created_by_job` matches `job_id`."""
        ...


class PromptRepository(Protocol):
    def put(self, prompt: Prompt) -> Prompt: ...

    def get(self, prompt_id: str) -> Prompt: ...

    def list(self) -> list[Prompt]: ...


class PromptExecutionRepository(Protocol):
    def put(self, execution: PromptExecution) -> PromptExecution: ...

    def list(self, *, limit: int | None = None) -> list[PromptExecution]: ...


class JobDefinitionRepository(Protocol):
    """Catalog of deployed JobDefinitions.

    Keyed `(name, version)` via the synthetic `id = "{name}@{version}"`.
    Bundle deploy writes here; API + worker consume (post-cutover) the
    same rows to discover what jobs exist.
    """

    def put(self, record: JobDefinitionRecord) -> JobDefinitionRecord:
        """Upsert by `id`. Re-deploying replaces the payload + bumps
        `deployed_at`. Returns the post-write record so callers see
        the canonical timestamp.
        """
        ...

    def get(self, definition_id: str) -> JobDefinitionRecord: ...

    def list(self, *, runtime_selector: str | None = None) -> list[JobDefinitionRecord]:
        """Every deployed definition, newest-first. Optional filter by
        `runtime_selector` for the worker-boot hot path (one query
        instead of fetch-all-then-filter).
        """
        ...

    def get_by_name(self, name: str) -> JobDefinitionRecord:
        """Latest-deployed record matching `name`. Raises ObjectNotFound
        if no version has been deployed.
        """
        ...


class ArtifactTypeRepository(Protocol):
    """Catalog of deployed ArtifactTypes (BaseArtifact subclasses).

    Same shape as [[JobDefinitionRepository]]: keyed `(name, version)`
    via `id = "{name}@{version}"`. Bundle deploy writes here; future
    SDK / worker code reads the JSON Schema to (de)serialize payloads
    without a static Python import.
    """

    def put(self, record: ArtifactTypeRecord) -> ArtifactTypeRecord: ...

    def get(self, type_id: str) -> ArtifactTypeRecord: ...

    def list(self, *, domain: str | None = None) -> list[ArtifactTypeRecord]: ...

    def get_by_name(self, name: str) -> ArtifactTypeRecord: ...


class CodePackageRepository(Protocol):
    """Catalog of installable code packages (wheels) keyed `(name, version)`.

    Bytes live in the FileRepository under the `code_packages` prefix;
    rows here carry the pointer + integrity metadata. Worker install
    (a follow-up slice) reads this catalog to know what to pip-install
    before resolving a JobDefinition's `code_entrypoint`.
    """

    def put(self, record: CodePackageRecord) -> CodePackageRecord: ...

    def get(self, package_id: str) -> CodePackageRecord: ...

    def list(self, *, runtime_selector: str | None = None) -> list[CodePackageRecord]: ...

    def get_by_name(self, name: str) -> CodePackageRecord: ...
