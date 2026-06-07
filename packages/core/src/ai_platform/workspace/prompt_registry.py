"""Prompt registry — high-level operations over the prompt store."""
from __future__ import annotations

from ai_platform.utilities.time import utc_now
from itertools import groupby
from operator import attrgetter
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from ai_platform.ai.prompts.models import Prompt, PromptExecution, PromptSnapshot
from ai_platform.workspace.prompt_repositories import B2PromptRepository, B2PromptExecutionRepository, LocalPromptRepository, LocalPromptExecutionRepository
from ai_platform.workspace.storage.exceptions import ObjectNotFound



def _version_tuple(version: str) -> tuple:
    """Convert '0.1.2' to (0, 1, 2) for sorting."""
    return tuple(int(p) for p in version.split("."))


class PromptRegistry:
    """Thin service layer wrapping a prompt repository."""

    def __init__(
        self,
        prompt_repo: Union[B2PromptRepository, LocalPromptRepository],
        *,
        execution_repo: Union[B2PromptExecutionRepository, LocalPromptExecutionRepository, None] = None,
    ) -> None:
        self._repo = prompt_repo
        self._execution_repo = execution_repo

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def _all_prompts(self) -> List[Prompt]:
        """Return every prompt version from the store."""
        return self._repo.list()

    def _latest_by_name(self, name: str) -> Prompt:
        """Filter all versions by name, return the one with the highest version."""
        matching = [p for p in self._all_prompts() if p.name == name]
        if not matching:
            raise ObjectNotFound(f"Prompt not found: {name}")
        matching.sort(key=lambda p: _version_tuple(p.version), reverse=True)
        return matching[0]

    def get_prompt(self, name: str) -> Prompt:
        """Return the latest version of a prompt by name."""
        return self._latest_by_name(name)

    def get_or_create(self, prompt: Prompt) -> Prompt:
        """Return the latest version if a prompt with this name exists, otherwise store it."""
        try:
            return self._latest_by_name(prompt.name)
        except ObjectNotFound:
            return self._repo.put(prompt)

    def update_instructions(self, name: str, new_instructions: str) -> Prompt:
        """Update the instructions of an existing prompt, bumping the version."""
        current = self._latest_by_name(name)
        updated = current.update_instructions(new_instructions)
        self._repo.put(updated)
        return updated

    def list_prompts(self, domain: Optional[str] = None) -> List[Prompt]:
        """Return the latest version of every prompt, optionally filtered by domain."""
        all_prompts = self._all_prompts()
        all_prompts.sort(key=attrgetter("name"))
        latest: List[Prompt] = []
        for _name, group in groupby(all_prompts, key=attrgetter("name")):
            versions = sorted(group, key=lambda p: _version_tuple(p.version), reverse=True)
            latest.append(versions[0])
        if domain is not None:
            latest = [p for p in latest if p.domain == domain]
        return latest

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self, name: str) -> PromptSnapshot:
        """Take a frozen snapshot of the current prompt version."""
        p = self.get_prompt(name)
        return PromptSnapshot(
            name=p.name,
            version=p.version,
            instructions=p.instructions,
        )

    # ------------------------------------------------------------------
    # Execution recording
    # ------------------------------------------------------------------

    def record_execution(
        self,
        prompt: Prompt,
        input_data: Dict[str, Any],
        *,
        model_name: Optional[str] = None,
        output_type: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> PromptExecution:
        """Create and persist an audit record for a prompt execution."""
        execution = PromptExecution(
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            input_data=input_data,
            executed_at=utc_now(),
            model_name=model_name,
            output_type=output_type,
            usage=usage,
        )
        if self._execution_repo is not None:
            self._execution_repo.put(execution)
        return execution

    def list_executions(self) -> List[PromptExecution]:
        """Return all recorded prompt executions."""
        if self._execution_repo is None:
            return []
        return self._execution_repo.list()
