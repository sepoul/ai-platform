"""Graph checkpoint container — the serialized resume point of a job run.

Deliberately engine-free (pydantic only, no `pydantic_graph`): the control
plane (`result_fetcher` → the API's `fetch_result`) parses the resume token
to read `artifact_refs` and must not drag the graph engine into the API.
The executor (`graph_execution`) re-exports this for its own use.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class GraphCheckpoint(BaseModel):
    """Checkpoint for resuming a pydantic_graph run."""

    state_data: dict[str, Any]
    next_node_key: str       # node class name to start from, or "__done__" when graph is finished
    gated_node: str | None = None   # class name of the node whose output is pending review
    attempt: int = 0
