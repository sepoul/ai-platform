"""CodePackage catalog — wheels (and other installable artifacts) that
back a JobDefinition's `code_entrypoint`.

Where JobDefinition records *what* a job is (its schemas) and
ArtifactType records *what it produces*, CodePackage records *what
to install* so the runtime can resolve the entrypoint.

The blob bytes (the actual `.whl`) live in the file repository; this
record carries the lightweight metadata: id, runtime, filename,
sha256, size, and the `blob_id` that maps back to the FileRepository.
Worker install (slice 4b — not in this PR) will fetch the blob and
`pip install` it before resolving `code_entrypoint`.

Today the row stands on its own: it's the substrate for the worker
install path, but nothing reads from it yet. POST is the friend-test
endpoint — a friend with their domain wheel + a JobDefinition POST
gets everything the platform needs to (eventually) run their code.
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


class CodePackageRecord(BaseModel):
    """Metadata pointer to an installable code blob.

    `blob_id` is the FileRepository logical name (filename within the
    `code_packages` prefix) — fetching the bytes goes through the
    file repository, not this record.
    """
    model_config = ConfigDict(extra="forbid")

    id: str  # "{name}@{version}"
    name: str  # distribution name, e.g. "mathai-math-qa"
    version: str = "1.0.0"
    runtime_selector: str  # which runtime should pip-install this
    filename: str  # original wheel filename, used to reconstruct the install
    blob_id: str  # FileRepository logical name within the code-packages prefix
    sha256: str  # integrity check; verified at fetch time
    size_bytes: int
    deployed_at: datetime = Field(default_factory=_utc_now)

    @classmethod
    def make_id(cls, name: str, version: str) -> str:
        return f"{name}@{version}"


class CodePackageStore(BaseModel):
    items: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=_utc_now)


class _CodePackageStoreMixin(SingleStoreMixin[Dict[str, Any], CodePackageStore]):
    model_cls = CodePackageStore
    missing_label = "CodePackage"

    def put(self, record: CodePackageRecord) -> CodePackageRecord:
        store = self._load_store()
        store.items[record.id] = record.model_dump(mode="json")
        self._save_store(store)
        return record

    def get(self, package_id: str) -> CodePackageRecord:
        store = self._load_store()
        if package_id not in store.items:
            raise ObjectNotFound(f"CodePackage not found: {package_id}")
        return CodePackageRecord.model_validate(store.items[package_id])

    def list(self, *, runtime_selector: Optional[str] = None) -> List[CodePackageRecord]:
        store = self._load_store()
        rows = [CodePackageRecord.model_validate(p) for p in store.items.values()]
        if runtime_selector is not None:
            rows = [r for r in rows if r.runtime_selector == runtime_selector]
        rows.sort(key=lambda r: r.deployed_at, reverse=True)
        return rows

    def get_by_name(self, name: str) -> CodePackageRecord:
        rows = [r for r in self.list() if r.name == name]
        if not rows:
            raise ObjectNotFound(f"No CodePackage named: {name}")
        return rows[0]


class B2CodePackageRepository(_CodePackageStoreMixin, B2CanonicalRepository):
    pass


class LocalCodePackageRepository(_CodePackageStoreMixin, LocalCanonicalRepository):
    pass
