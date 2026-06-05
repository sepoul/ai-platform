"""JobDefinition catalog — the persisted shadow of a JobControl.

A JobControl today lives in code (declared by a domain's `register_control`).
The platform discovers it at API boot via `composition_root`. That works,
but it means a friend can't "deploy" a new domain to a running platform
without rebuilding the api+worker images that statically import the
domain.

This module is the storage substrate that lets bundle deployment push
JobControls into the platform's catalog at runtime. A `JobDefinitionRecord`
captures everything the API needs to register a job (schemas, gates,
runtime selector, code entrypoint) as plain data — no Python types.
The next PR will migrate the API to consult this catalog instead of the
in-memory `_job_controls` dict; for now the row is recorded as a parallel
artifact of the deploy and the runtime still uses the in-code path.
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


# ---------------------------------------------------------------------------
# Record shape
# ---------------------------------------------------------------------------


class GateSpec(BaseModel):
    """A single human-review gate carried by a JobDefinition.

    `review_schema` is the pydantic `model_json_schema()` of the review
    body — the API uses it to validate `POST /jobs/{id}/review` once the
    catalog drives routing. For now it's recorded for completeness.
    """
    model_config = ConfigDict(extra="forbid")

    node_name: str
    review_type_name: str
    review_schema: Dict[str, Any]


class JobDefinitionRecord(BaseModel):
    """Plain-data record of a job's control plane.

    Keyed `(name, version)`. The id is the derived `"{name}@{version}"`
    string; downstream callers reference it by `id` (versioned) or by
    `name` (latest) depending on the path.
    """
    model_config = ConfigDict(extra="forbid")

    id: str  # "{name}@{version}"
    name: str
    version: str = "1.0.0"
    # Permissive str: the model accepts any runtime selector. The
    # JobDefinitionService validates against the platform's known
    # runtimes (KNOWN_RUNTIMES) at deploy time — keeps the catalog
    # forward-compatible with new runtimes without re-deploying the
    # API schema.
    runtime_selector: str
    # Execution-plane entrypoint string ("package.module:callable", e.g.
    # "mathai.math_qa.execution:register_execution"). The worker imports
    # this after the catalog install pass + registers the JobExecution.
    code_entrypoint: str
    # Control-plane entrypoint ("package.module:callable" pointing at the
    # `register_control(ctx) -> ControlDomain` callable, e.g.
    # "mathai.math_qa.control:register_control"). The API imports this
    # after `install_control_packages_for_api` + registers the JobControl.
    # Default empty for backward-compat with rows written before this field
    # existed; the API's auto-deploy on next boot will overwrite them.
    control_entrypoint: str = ""
    label: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)  # JSON Schema from model_json_schema()
    result_schema: Dict[str, Any] = Field(default_factory=dict)
    output_artifact_type_refs: List[str] = Field(default_factory=list)
    gates: List[GateSpec] = Field(default_factory=list)
    deployed_at: datetime = Field(default_factory=_utc_now)

    @classmethod
    def make_id(cls, name: str, version: str) -> str:
        return f"{name}@{version}"


# ---------------------------------------------------------------------------
# Single-blob store (local + B2 backing)
# ---------------------------------------------------------------------------


class JobDefinitionStore(BaseModel):
    """All job-definition records, single JSON blob keyed by id."""
    items: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=_utc_now)


class _JobDefinitionStoreMixin(SingleStoreMixin[Dict[str, Any], JobDefinitionStore]):
    """Shared local + B2 implementation. Same single-blob shape the
    artifacts repo uses; cheap per-write read-modify-write at our scale.
    """
    model_cls = JobDefinitionStore
    missing_label = "JobDefinition"

    # ---- Protocol surface ----

    def put(self, record: JobDefinitionRecord) -> JobDefinitionRecord:
        store = self._load_store()
        store.items[record.id] = record.model_dump(mode="json")
        self._save_store(store)
        return record

    def get(self, definition_id: str) -> JobDefinitionRecord:
        store = self._load_store()
        if definition_id not in store.items:
            raise ObjectNotFound(f"JobDefinition not found: {definition_id}")
        return JobDefinitionRecord.model_validate(store.items[definition_id])

    def list(self, *, runtime_selector: Optional[str] = None) -> List[JobDefinitionRecord]:
        store = self._load_store()
        rows = [JobDefinitionRecord.model_validate(p) for p in store.items.values()]
        if runtime_selector is not None:
            rows = [r for r in rows if r.runtime_selector == runtime_selector]
        rows.sort(key=lambda r: r.deployed_at, reverse=True)
        return rows

    def get_by_name(self, name: str) -> JobDefinitionRecord:
        """Return the latest-deployed record for `name`. Convenience
        for the routing path (post-cutover) which doesn't yet care about
        version pinning. Raises ObjectNotFound if none exist.
        """
        rows = [r for r in self.list() if r.name == name]
        if not rows:
            raise ObjectNotFound(f"No JobDefinition named: {name}")
        return rows[0]  # `list()` returns newest-first


class B2JobDefinitionRepository(_JobDefinitionStoreMixin, B2CanonicalRepository):
    pass


class LocalJobDefinitionRepository(_JobDefinitionStoreMixin, LocalCanonicalRepository):
    pass
