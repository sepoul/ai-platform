from __future__ import annotations
from datetime import datetime

from ai_platform.utilities.time import utc_now
from enum import Enum
from typing import Any, Dict, List
from uuid import UUID, uuid4
from pydantic import BaseModel, Field
from ai_platform.workspace.storage.structured.b2 import B2CanonicalRepository
from ai_platform.workspace.storage.structured.local import LocalCanonicalRepository
from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.structured.base import StoredRecord


# ---------------------------------------------------------------------------
# Simplified job models (stripped-down specs.py)
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_INPUT = "WAITING_INPUT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobSpec(BaseModel):
    """Immutable job intent -- minimal version."""

    job_id: UUID = Field(default_factory=uuid4)
    job_type: str
    created_at: datetime = Field(default_factory=utc_now)
    created_by: str | None = None
    workspace_ref: str | None = None

    graph_ref: str  # e.g. "math_qa_graph"
    input_payload: dict[str, Any] | None = None
    priority: int = 0
    idempotency_key: str | None = None

    # simple constraints
    max_attempts: int = Field(default=3, ge=1)
    timeout_seconds: int = Field(default=3600, ge=1)


class JobState(BaseModel):
    """Mutable runtime state."""

    job_id: UUID
    status: JobStatus = JobStatus.PENDING
    updated_at: datetime = Field(default_factory=utc_now)
    version: int = Field(default=0, ge=0)
    attempt: int = Field(default=0, ge=0)

    claimed_by: str | None = None
    heartbeat_at: datetime | None = None

    # progress
    stage: str | None = None
    percent: float | None = None
    message: str | None = None

    # result / error
    result_payload: dict[str, Any] | None = None
    # IDs of the artifacts the persistence callback minted for this job —
    # the durable, domain-agnostic source of truth for
    # `GET /jobs/{id}/result` hydration. Copied from the execution state's
    # `artifact_refs` at completion (`mark_succeeded`) so it survives
    # `complete_job`'s record re-read, instead of depending on each
    # domain's `extract_result` echoing refs into `result_payload`.
    artifact_refs: list[UUID] = Field(default_factory=list)
    error_message: str | None = None
    error_retryable: bool = False

    # waiting for human input
    waiting_for: str | None = None  # e.g. "human_review_signals"
    resume_token: str | None = None
    # A human review submitted via the API but not yet applied to graph
    # state. The API only validates + stores the raw payload here (it has
    # no business deserializing the execution state model); the worker
    # merges it into state on resume and clears this. See job_runner.
    pending_review: dict[str, Any] | None = None

    cancel_requested: bool = False


class JobRecord(BaseModel):
    """Single combined record for storage."""

    spec: JobSpec
    state: JobState
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        job_type: str,
        graph_ref: str,
        input_payload: dict[str, Any] | None = None,
        workspace_ref: str | None = None,
        created_by: str | None = None,
    ) -> "JobRecord":
        job_id = uuid4()
        spec = JobSpec(
            job_id=job_id,
            job_type=job_type,
            graph_ref=graph_ref,
            input_payload=input_payload,
            workspace_ref=workspace_ref,
            created_by=created_by,
        )
        state = JobState(job_id=job_id)
        return cls(spec=spec, state=state)

    def mark_running(self, worker_id: str | None = None) -> None:
        self.state.status = JobStatus.RUNNING
        self.state.attempt += 1
        self.state.claimed_by = worker_id
        self.state.heartbeat_at = utc_now()
        self._bump()

    def mark_waiting(self, reason: str, resume_token: str | None = None) -> None:
        self.state.status = JobStatus.WAITING_INPUT
        self.state.waiting_for = reason
        self.state.resume_token = resume_token
        self._bump()

    def mark_succeeded(
        self,
        result: dict[str, Any] | None = None,
        artifact_refs: list[UUID] | None = None,
    ) -> None:
        self.state.status = JobStatus.SUCCEEDED
        self.state.result_payload = result
        # Persist the minted refs onto the record itself — written in the
        # same `put` as the SUCCEEDED status, so a reader never sees a
        # completed job without its refs.
        if artifact_refs is not None:
            self.state.artifact_refs = list(artifact_refs)
        self._bump()

    def mark_failed(self, error: str, retryable: bool = False) -> None:
        self.state.status = JobStatus.FAILED
        self.state.error_message = error
        self.state.error_retryable = retryable
        self._bump()

    def mark_cancelled(self) -> None:
        self.state.status = JobStatus.CANCELLED
        self._bump()

    def update_progress(self, stage: str | None = None, percent: float | None = None, message: str | None = None) -> None:
        self.state.stage = stage
        self.state.percent = percent
        self.state.message = message
        self._bump()

    def _bump(self) -> None:
        now = utc_now()
        self.state.version += 1
        self.state.updated_at = now
        self.updated_at = now


# ---------------------------------------------------------------------------
# Store wrapper (single-file pattern)
# ---------------------------------------------------------------------------

class JobStore(BaseModel):
    """All jobs in one JSON blob."""

    items: Dict[str, JobRecord] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Job store mixin (defined here to avoid circular imports with store_mixins.py)
# ---------------------------------------------------------------------------

class _JobStoreMixin:
    """
    Store-pattern mixin for job repositories.
    super() calls resolve via MRO to whichever concrete backend follows.
    """

    model_cls = JobStore
    STORE_KEY = "__store__"

    def _load_store(self) -> JobStore:
        try:
            return super().get_canonical(self.STORE_KEY).data
        except ObjectNotFound:
            return JobStore()

    def _save_store(self, store: JobStore) -> StoredRecord[JobStore]:
        store.updated_at = utc_now()
        return super().put_canonical(self.STORE_KEY, store)

    # ---- Protocol surface ----
    # See `ai_platform.workspace.storage.protocols.JobRepository`. The
    # single-blob store backing this is a private impl detail of the
    # local + B2 backends; callers only see put/get/list/delete.

    def put(self, record: JobRecord, *, expected_version: int | None = None) -> JobRecord:
        # Single-blob stores can't enforce the concurrency check
        # atomically — the read-modify-write of the entire store is
        # not isolated. We accept the kwarg for Protocol conformance
        # and ignore it. Tracked as tech debt in NEXT_BEST_STEPS.md.
        key = str(record.spec.job_id)
        store = self._load_store()
        store.items[key] = record
        self._save_store(store)
        return record

    def get(self, job_id: str | UUID) -> JobRecord:
        key = str(job_id)
        store = self._load_store()
        if key not in store.items:
            raise ObjectNotFound(f"Job not found: {key}")
        return store.items[key]

    def list(
        self,
        *,
        status: JobStatus | None = None,
        job_type: str | None = None,
        limit: int | None = None,
    ) -> List[JobRecord]:
        store = self._load_store()
        results = list(store.items.values())
        if status is not None:
            results = [r for r in results if r.state.status == status]
        if job_type is not None:
            results = [r for r in results if r.spec.job_type == job_type]
        # newest first
        results.sort(key=lambda r: r.created_at, reverse=True)
        if limit is not None:
            results = results[:limit]
        return results

    def delete(self, job_id: str | UUID) -> None:
        key = str(job_id)
        store = self._load_store()
        if key in store.items:
            del store.items[key]
            self._save_store(store)


# ---------------------------------------------------------------------------
# Repository classes
# ---------------------------------------------------------------------------

class B2JobRepository(_JobStoreMixin, B2CanonicalRepository):
    pass


class LocalJobRepository(_JobStoreMixin, LocalCanonicalRepository):
    pass
