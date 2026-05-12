"""Generic artifact storage.

A single workspace-wide store keyed on `artifact_id`. Values are stored
as raw dicts (the `model_dump()` of a `BaseArtifact` subclass); the
domain-specific registry decides how to hydrate them back into typed
artifacts on read.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from pydantic import BaseModel, Field

from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.mixins import SingleStoreMixin
from ai_platform.workspace.storage.structured.b2 import B2CanonicalRepository
from ai_platform.workspace.storage.structured.local import LocalCanonicalRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ArtifactStore(BaseModel):
    """Single JSON blob holding every artifact in the workspace.

    The `items` mapping uses `artifact_id` (string form of UUID) as the
    key and the artifact's `model_dump(mode="json")` as the value. The
    `artifact_type` field on each value is the discriminator a registry
    uses to hydrate.
    """

    items: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=_utc_now)


class _ArtifactStoreMixin(SingleStoreMixin[Dict[str, Any], ArtifactStore]):
    model_cls = ArtifactStore
    missing_label = "ArtifactStore"

    # ---- Protocol surface ----
    # See `ai_platform.workspace.storage.protocols.ArtifactRepository`.
    # Reads/writes the raw payload dict directly — `StoredRecord[T]`'s
    # generic `data: T` coerces dicts into an empty BaseModel, so we
    # bypass it and talk to the underlying store. Hydration into
    # `BaseArtifact` lives in `ArtifactService`.

    def put(self, artifact_id: str, payload: dict) -> None:
        store = self._load_store()
        store.items[artifact_id] = payload
        self._save_store(store)

    def get(self, artifact_id: str) -> dict:
        store = self._load_store()
        if artifact_id not in store.items:
            raise ObjectNotFound(f"Artifact not found: {artifact_id}")
        return store.items[artifact_id]

    def list_ids(self) -> list[str]:
        return self.list_canonicals()


class B2ArtifactRepository(_ArtifactStoreMixin, B2CanonicalRepository):
    pass


class LocalArtifactRepository(_ArtifactStoreMixin, LocalCanonicalRepository):
    pass
