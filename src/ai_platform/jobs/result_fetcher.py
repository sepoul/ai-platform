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
from ai_platform.jobs.graph_execution import GraphCheckpoint


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
    token = getattr(record.state, "resume_token", None)
    if token:
        try:
            ckpt = GraphCheckpoint.model_validate_json(token)
            raw = ckpt.state_data.get("artifact_refs") or []
            return [UUID(str(x)) for x in raw]
        except Exception:
            pass

    payload = record.state.result_payload or {}
    raw = payload.get("artifact_refs") or []
    return [UUID(str(x)) for x in raw]
