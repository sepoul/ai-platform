"""Workspace API dependencies — math QA domain singleton."""
from __future__ import annotations

from typing import Optional

from mathai.workspace.client import MathWorkspaceClient


_workspace_client: Optional[MathWorkspaceClient] = None


def init_workspace(workspace_client: MathWorkspaceClient) -> None:
    global _workspace_client
    _workspace_client = workspace_client


def get_workspace_client() -> MathWorkspaceClient:
    if _workspace_client is None:
        raise RuntimeError("Workspace not initialized — call init_workspace() first")
    return _workspace_client
