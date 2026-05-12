from __future__ import annotations
from typing import Any, Protocol, TypeVar
from uuid import UUID
from pydantic import BaseModel
from pydantic_graph import BaseNode, End

from ai_platform.workspace.storage.protocols import JobRepository
from ai_platform.workspace.storage.structured.job_repository import JobRecord, JobStatus


# ---------------------------------------------------------------------------
# Generic graph checkpoint container
# ---------------------------------------------------------------------------

class GraphCheckpoint(BaseModel):
    """Checkpoint for resuming a pydantic_graph run."""

    state_data: dict[str, Any]
    next_node_key: str       # node class name to start from, or "__done__" when graph is finished
    gated_node: str | None = None   # class name of the node whose output is pending review
    attempt: int = 0


# ---------------------------------------------------------------------------
# Graph runner protocol
# ---------------------------------------------------------------------------

StateT = TypeVar("StateT", bound=BaseModel)
DepsT = TypeVar("DepsT")
OutputT = TypeVar("OutputT")


class GraphRunner(Protocol[StateT, DepsT, OutputT]):
    """
    Protocol for any graph-based runner.
    Expects: start_run, step, resume.
    """

    async def step(
        self, deps: DepsT, state: StateT, **kwargs: Any
    ) -> End[OutputT] | BaseNode[StateT, DepsT]:
        """Run one step of the graph. Return End if done, else next node."""
        ...


# ---------------------------------------------------------------------------
# Job-graph bridge
# ---------------------------------------------------------------------------

class GraphJobExecutor:
    """
    Thin layer to execute pydantic_graph-based jobs stored in a JobRepository.
    """

    def __init__(self, job_repo: JobRepository):
        self.repo = job_repo

    def submit_graph_job(
        self,
        job_type: str,
        graph_ref: str,
        initial_state: dict[str, Any],
        deps_payload: dict[str, Any] | None = None,
        workspace_ref: str | None = None,
        created_by: str | None = None,
    ) -> JobRecord:
        """
        Submit a new job for a graph run.
        initial_state: serialized pydantic state (e.g. MathQAState.model_dump())
        deps_payload: serialized dependencies (e.g. InputsSourcer params)
        """
        record = JobRecord.create(
            job_type=job_type,
            graph_ref=graph_ref,
            input_payload={"state": initial_state, "deps": deps_payload or {}},
            workspace_ref=workspace_ref,
            created_by=created_by,
        )
        self.repo.put(record)
        return record

    def mark_running(self, job_id: str | UUID, worker_id: str | None = None) -> JobRecord:
        """Claim job and mark it running."""
        record = self.repo.get(job_id)
        record.mark_running(worker_id=worker_id)
        self.repo.put(record)
        return record

    def save_checkpoint(
        self,
        job_id: str | UUID,
        state: dict[str, Any],
        next_node_key: str,
        reason: str | None = None,
        gated_node: str | None = None,
    ) -> JobRecord:
        """Pause job with checkpoint for resumption (status → WAITING_INPUT)."""
        record = self.repo.get(job_id)
        checkpoint = GraphCheckpoint(
            state_data=state,
            next_node_key=next_node_key,
            gated_node=gated_node,
            attempt=record.state.attempt,
        )
        record.mark_waiting(reason=reason or "checkpoint", resume_token=checkpoint.model_dump_json())
        self.repo.put(record)
        return record

    def load_checkpoint(self, job_id: str | UUID) -> GraphCheckpoint | None:
        """Load checkpoint from job.state.resume_token if present."""
        record = self.repo.get(job_id)
        if not record.state.resume_token:
            return None
        return GraphCheckpoint.model_validate_json(record.state.resume_token)

    def complete_job(
        self,
        job_id: str | UUID,
        result: dict[str, Any] | None = None,
    ) -> JobRecord:
        """Mark job as succeeded with final result."""
        record = self.repo.get(job_id)
        record.mark_succeeded(result=result)
        record.state.stage = "completed"
        record.state.percent = 100.0
        record.state.message = "Job completed successfully"
        self.repo.put(record)
        return record

    def fail_job(
        self,
        job_id: str | UUID,
        error: str,
        retryable: bool = False,
    ) -> JobRecord:
        """Mark job as failed."""
        record = self.repo.get(job_id)
        record.mark_failed(error=error, retryable=retryable)
        self.repo.put(record)
        return record

    def update_progress(
        self,
        job_id: str | UUID,
        stage: str | None = None,
        percent: float | None = None,
        message: str | None = None,
    ) -> JobRecord:
        """Update job progress metadata."""
        record = self.repo.get(job_id)
        record.update_progress(stage=stage, percent=percent, message=message)
        self.repo.put(record)
        return record

    def claim_next_pending(
        self,
        job_type: str | None = None,
        worker_id: str | None = None,
    ) -> JobRecord | None:
        """
        Simple claim: find first PENDING job (optionally filtered by type),
        mark RUNNING and return it.
        Returns None if no jobs available.
        """
        jobs = self.repo.list(status=JobStatus.PENDING, job_type=job_type, limit=1)
        if not jobs:
            return None
        record = jobs[0]
        record.mark_running(worker_id=worker_id)
        self.repo.put(record)
        return record

    def list_waiting_jobs(self, job_type: str | None = None) -> list[JobRecord]:
        """List all jobs waiting for input/review."""
        return self.repo.list(status=JobStatus.WAITING_INPUT, job_type=job_type)




