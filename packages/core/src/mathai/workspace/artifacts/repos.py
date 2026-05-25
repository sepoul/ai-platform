"""Backwards-friendly re-exports of the platform artifact repos.

The math workspace doesn't own its own artifact storage anymore — it
uses the platform's generic artifact repository directly. Kept as a thin
re-export so existing imports remain stable.
"""
from ai_platform.workspace.storage.structured.artifact_repository import (
    B2ArtifactRepository,
    LocalArtifactRepository,
)

__all__ = ["B2ArtifactRepository", "LocalArtifactRepository"]
