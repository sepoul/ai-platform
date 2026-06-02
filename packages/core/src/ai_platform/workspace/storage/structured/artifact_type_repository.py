"""ArtifactType catalog — the persisted shadow of a BaseArtifact class.

Mirror shape of `job_definition_repository`. Where JobDefinition is
the schema for a *runnable*, ArtifactType is the schema for an
*output* — a typed payload a job produces.

A BaseArtifact subclass today is purely a Python class registered on
the in-memory `ArtifactService` registry. The friend-test problem is
the same as for JobDefinitions: a friend's domain can't introduce a
new artifact type without rebuilding the api/worker images that
import its class.

This module gives the catalog a row per artifact type so:
1. Bundle deploy can register new types over HTTP.
2. The API can list every type's schema for UI / SDK consumers.
3. Future code-package upload can install the BaseArtifact subclass
   into a running worker keyed on the catalog row.

Today the row is recorded but doesn't drive hydration (that still uses
the in-memory `ArtifactService.registry`). Cutover lands when wheel
upload does.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.mixins import SingleStoreMixin
from ai_platform.workspace.storage.structured.b2 import B2CanonicalRepository
from ai_platform.workspace.storage.structured.local import LocalCanonicalRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ArtifactTypeRecord(BaseModel):
    """Plain-data record for an artifact type.

    Keyed `(name, version)` where `name` is the discriminator string
    (e.g. "math_question", "ai_answer", "math_conversation") and
    version follows the same defaulting story as JobDefinition.
    """
    model_config = ConfigDict(extra="forbid")

    id: str  # "{name}@{version}"
    name: str  # the artifact_type discriminator
    version: str = "1.0.0"
    domain: str  # owning domain (e.g. "math_qa") — informational
    class_name: str  # the Python class name (e.g. "MathQuestionArtifact")
    json_schema: Dict[str, Any] = Field(default_factory=dict)
    display_hints: Dict[str, Any] = Field(default_factory=dict)
    deployed_at: datetime = Field(default_factory=_utc_now)

    @classmethod
    def make_id(cls, name: str, version: str) -> str:
        return f"{name}@{version}"


# ---------------------------------------------------------------------------
# Single-blob store (local + B2)
# ---------------------------------------------------------------------------


class ArtifactTypeStore(BaseModel):
    items: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=_utc_now)


class _ArtifactTypeStoreMixin(SingleStoreMixin[Dict[str, Any], ArtifactTypeStore]):
    model_cls = ArtifactTypeStore
    missing_label = "ArtifactType"

    def put(self, record: ArtifactTypeRecord) -> ArtifactTypeRecord:
        store = self._load_store()
        store.items[record.id] = record.model_dump(mode="json")
        self._save_store(store)
        return record

    def get(self, type_id: str) -> ArtifactTypeRecord:
        store = self._load_store()
        if type_id not in store.items:
            raise ObjectNotFound(f"ArtifactType not found: {type_id}")
        return ArtifactTypeRecord.model_validate(store.items[type_id])

    def list(self, *, domain: Optional[str] = None) -> List[ArtifactTypeRecord]:
        store = self._load_store()
        rows = [ArtifactTypeRecord.model_validate(p) for p in store.items.values()]
        if domain is not None:
            rows = [r for r in rows if r.domain == domain]
        rows.sort(key=lambda r: r.deployed_at, reverse=True)
        return rows

    def get_by_name(self, name: str) -> ArtifactTypeRecord:
        rows = [r for r in self.list() if r.name == name]
        if not rows:
            raise ObjectNotFound(f"No ArtifactType named: {name}")
        return rows[0]


class B2ArtifactTypeRepository(_ArtifactTypeStoreMixin, B2CanonicalRepository):
    pass


class LocalArtifactTypeRepository(_ArtifactTypeStoreMixin, LocalCanonicalRepository):
    pass
