"""Workspace-side artifact API.

Wraps a generic ArtifactRepository and uses a registry mapping
`artifact_type` strings to concrete `BaseArtifact` subclasses to hydrate
stored payloads back into typed artifacts.
"""
from __future__ import annotations

import re
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
            # `storage_url` is a read-side hydration of `storage_ref`
            # (see BaseArtifact); it's recomputed on GET and never stored.
            artifact.model_dump(mode="json", exclude={"storage_url"}),
        )
        return artifact.artifact_id

    def get(self, artifact_id: UUID | str) -> BaseArtifact:
        return self._hydrate(self.repo.get(str(artifact_id)))

    def get_many(self, ids: Iterable[UUID | str]) -> list[BaseArtifact]:
        """Batch-hydrate by id. One round-trip on Supabase (was: one
        per id). Preserves input order and raises `ObjectNotFound`
        listing every missing id — same fail-loud contract as the
        prior per-id loop, so callers that rely on "all-or-nothing"
        keep working.
        """
        from ai_platform.workspace.storage.exceptions import ObjectNotFound

        str_ids = [str(i) for i in ids]
        if not str_ids:
            return []
        payloads = self.repo.get_many(str_ids)
        by_id = {p["artifact_id"]: p for p in payloads}
        missing = [i for i in str_ids if i not in by_id]
        if missing:
            raise ObjectNotFound(f"Artifacts not found: {missing}")
        return [self._hydrate(by_id[i]) for i in str_ids]

    # ---- Batched list_* — single round-trip on Supabase ----
    # Replaces the old `for raw_id in repo.list_ids(): self.get(raw_id)`
    # pattern that did one round-trip per artifact. Unknown
    # `artifact_type` discriminators are skipped (resilient to a
    # registered-and-then-removed domain) rather than raising, which
    # mirrors the artifacts router's prior loop behavior.

    def list_all(self, *, limit: int | None = None) -> list[BaseArtifact]:
        return self._hydrate_many(self.repo.list_all(limit=limit))

    def list_by_type(self, artifact_type: str, *, limit: int | None = None) -> list[BaseArtifact]:
        return self._hydrate_many(self.repo.list_by_type(artifact_type, limit=limit))

    def list_by_job(self, job_id: UUID | str, *, limit: int | None = None) -> list[BaseArtifact]:
        return self._hydrate_many(self.repo.list_by_job(str(job_id), limit=limit))

    def query(
        self,
        *,
        artifact_type: str | None = None,
        job_id: UUID | str | None = None,
        fields: dict[str, str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[BaseArtifact]:
        """Filtered, paginated read — the engine behind `GET /artifacts`.

        `fields` is an equality filter on top-level domain fields (e.g.
        `{"source_note_id": "<id>"}`); each key is validated against the
        registry whitelist before it reaches the backend query, so callers
        can't filter on (or inject via) arbitrary names. Returns typed,
        newest-first artifacts.
        """
        safe_fields = self._validate_filter_fields(artifact_type, fields) if fields else None
        return self._hydrate_many(
            self.repo.query(
                artifact_type=artifact_type,
                job_id=str(job_id) if job_id is not None else None,
                fields=safe_fields,
                limit=limit,
                offset=offset,
            )
        )

    # Field names must be plain identifiers (defense-in-depth — they also
    # bind as SQL parameters, never interpolated).
    _FIELD_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

    def _allowed_filter_fields(self, artifact_type: str | None) -> set[str]:
        """Whitelist of filterable field names. Scoped to one type's
        declared fields when `artifact_type` is given, else the union of
        every registered type's fields."""
        if artifact_type is not None:
            cls = self.registry.get(artifact_type)
            return set(cls.model_fields) if cls is not None else set()
        allowed: set[str] = set()
        for cls in self.registry.values():
            allowed |= set(cls.model_fields)
        return allowed

    def _validate_filter_fields(
        self, artifact_type: str | None, fields: dict[str, str]
    ) -> dict[str, str]:
        allowed = self._allowed_filter_fields(artifact_type)
        validated: dict[str, str] = {}
        for key, value in fields.items():
            if not self._FIELD_NAME.match(key):
                raise ValueError(f"Invalid filter field name: {key!r}")
            if key not in allowed:
                scope = f" on artifact_type={artifact_type!r}" if artifact_type else ""
                raise ValueError(f"Field {key!r} is not filterable{scope}")
            validated[key] = value
        return validated

    def _hydrate_many(self, payloads: list[dict]) -> list[BaseArtifact]:
        out: list[BaseArtifact] = []
        for raw in payloads:
            try:
                out.append(self._hydrate(raw))
            except ValueError:
                # Unknown artifact_type (e.g. a domain was unregistered
                # after the row was written). Skip silently to match the
                # router's existing resilience contract.
                continue
        return out

    def _hydrate(self, raw: dict) -> BaseArtifact:
        artifact_type = raw.get("artifact_type")
        cls = self.registry.get(artifact_type)
        if cls is None:
            raise ValueError(f"No registered class for artifact_type={artifact_type!r}")
        return cls.model_validate(raw)
