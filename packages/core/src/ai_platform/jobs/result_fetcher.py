"""Generic result fetcher — hydrates artifacts referenced by a JobRecord.

Domains can call this from their `JobDefinition.fetch_result` to convert
`record.state.artifact_refs` into typed artifacts, then assemble the
domain-specific `BaseJobResult`.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.jobs.checkpoint import GraphCheckpoint


def hydrate_artifact_refs(
    record: Any,
    artifact_api: ArtifactService,
) -> list[BaseArtifact]:
    """Return the typed artifacts referenced by `record`.

    Refs are read from the in-state checkpoint (resume_token) when
    available, falling back to the result payload, falling back to an
    empty list when the job hasn't reached a persistence point yet.
    """
    ids = _extract_refs(record)
    if not ids:
        return []
    return artifact_api.get_many(ids)


def _extract_refs(record: Any) -> list[UUID]:
    # Primary, authoritative source: the refs `mark_succeeded` persisted onto
    # the record at completion (PR-3e). Written atomically with the SUCCEEDED
    # status and independent of the domain's `extract_result`, so a completed
    # job always carries its refs. The checkpoint / result_payload reads below
    # remain as fallbacks for records written before this field existed and for
    # gated jobs read mid-flight (status not yet SUCCEEDED).
    persisted = getattr(record.state, "artifact_refs", None)
    if persisted:
        return [UUID(str(x)) for x in persisted]

    token = getattr(record.state, "resume_token", None)
    if token:
        try:
            ckpt = GraphCheckpoint.model_validate_json(token)
            raw = ckpt.state_data.get("artifact_refs") or []
            # Only let the checkpoint win when it actually carries refs. For an
            # ungated single-node job the checkpoint is saved *before* the
            # End → persist step appends the minted ids, so its `artifact_refs`
            # is empty; falling through to `result_payload` (which the job's
            # `extract_result` populates from `state.artifact_refs`) is what
            # lets `GET /jobs/{id}/result` hydrate those artifacts. A
            # gated/resumed job's checkpoint does carry refs and still wins.
            if raw:
                return [UUID(str(x)) for x in raw]
        except Exception:
            pass

    payload = record.state.result_payload or {}
    raw = payload.get("artifact_refs") or []
    return [UUID(str(x)) for x in raw]
