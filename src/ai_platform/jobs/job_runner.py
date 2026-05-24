"""Generic graph job handler — drives any JobDefinition through its graph."""
from __future__ import annotations

import logging

from pydantic_graph import End

from ai_platform.jobs.execution_policy import JobDefinition
from ai_platform.jobs.graph_execution import GraphJobExecutor
from ai_platform.workspace.storage.structured.job_repository import JobRecord

logger = logging.getLogger(__name__)

# Sentinel stored as next_node_key when the graph has finished computing but
# is still waiting for a human review before the job can be marked complete.
SENTINEL_DONE = "__done__"


async def run_graph_job(
    record: JobRecord,
    executor: GraphJobExecutor,
    job_def: JobDefinition,
) -> None:
    job_id = str(record.spec.job_id)
    deps_payload = (record.spec.input_payload or {}).get("deps", {})

    checkpoint = executor.load_checkpoint(job_id)
    if checkpoint:
        state = job_def.state_type.model_validate(checkpoint.state_data)

        # Apply any human review the API stored on the record (review-as-data).
        # The API only validated + parked the raw payload; merging it into the
        # execution state model is the worker's job. Clear it once applied so a
        # later gate can't re-consume a stale review.
        pending = record.state.pending_review
        if pending and checkpoint.gated_node:
            gate = job_def.policy.gate_for(checkpoint.gated_node)
            if gate:
                review = gate.review_type.model_validate(pending)
                state.set_review(checkpoint.gated_node, review)
                record.state.pending_review = None
                record._bump()
                executor.repo.put(record)

        if checkpoint.next_node_key == SENTINEL_DONE:
            _run_persist(job_def.persistence.on_complete, job_id, state)
            result = job_def.extract_result(state)
            executor.complete_job(job_id, result=result.model_dump(mode="json"))
            logger.info("Job %s: completed after review", job_id)
            return

        node_cls = job_def.node_registry.get(checkpoint.next_node_key)
        if node_cls is None:
            executor.fail_job(job_id, error=f"Unknown node key in checkpoint: {checkpoint.next_node_key}")
            return
        node = node_cls()
        logger.info("Job %s: resuming at %s", job_id, checkpoint.next_node_key)
    else:
        state = job_def.state_type()
        node = job_def.node_registry[job_def.start_node_key]()
        logger.info("Job %s: fresh start at %s", job_id, job_def.start_node_key)

    # `_job_id` is the runner-injected key used by deps factories that
    # want to construct a per-job WorkerLogger. Domain code reads it
    # via `payload.get("_job_id")` — invisible to graph nodes.
    deps_payload = {**deps_payload, "_job_id": job_id}
    deps = job_def.deps_factory(deps_payload)

    current_node = node
    async with job_def.graph.iter(node, state=state, deps=deps) as run:
        while True:
            prev_node_name = type(current_node).__name__
            current_node = await run.next()

            gate = job_def.policy.gate_for(prev_node_name)
            if gate and not state.has_review(prev_node_name):
                next_key = SENTINEL_DONE if isinstance(current_node, End) else type(current_node).__name__
                _run_persist(job_def.persistence.on_pause, job_id, state)
                executor.save_checkpoint(
                    job_id=job_id,
                    state=state.model_dump(),
                    next_node_key=next_key,
                    gated_node=prev_node_name,
                    reason=gate.node_name,
                )
                executor.update_progress(
                    job_id,
                    stage=prev_node_name,
                    message=f"Waiting for review of {prev_node_name}",
                )
                logger.info("Job %s: paused — waiting for review of %s", job_id, prev_node_name)
                return

            if isinstance(current_node, End):
                _run_persist(job_def.persistence.on_complete, job_id, state)
                result = job_def.extract_result(state)
                executor.complete_job(job_id, result=result.model_dump(mode="json"))
                logger.info("Job %s: completed", job_id)
                return

            executor.update_progress(
                job_id,
                stage=type(current_node).__name__,
                message=f"Running {type(current_node).__name__}",
            )


def _run_persist(callback, job_id: str, state) -> None:
    """Invoke a persistence callback and append minted artifact IDs to state.

    Callback signature: `(job_id, state) -> list[UUID]`. Exceptions
    propagate: with artifacts as first-class outputs, a silent failure
    here means `fetch_result` 404s on a "SUCCEEDED" job. The outer
    worker loop catches and marks the job FAILED with full traceback.
    """
    if callback is None:
        return
    new_ids = callback(job_id, state) or []
    if new_ids:
        state.artifact_refs.extend(new_ids)
