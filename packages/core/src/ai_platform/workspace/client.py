from ai_platform.workspace.prompt_registry import PromptRegistry
from ai_platform.workspace.storage.backends import Backend
from ai_platform.workspace.storage.blobs.base import FileRepository
from ai_platform.workspace.storage.protocols import (
    PromptExecutionRepository,
    PromptRepository,
)


class PlatformClient:
    """Workspace facade for prompts + files.

    The job and artifact repositories are wired through the platform
    bootstrap separately (see `bootstrap_workspace`). Construction is
    backend-agnostic — a `Backend` produces every repo and this class
    just composes the prompt registry on top.
    """

    def __init__(
        self,
        prompt_repo: PromptRepository,
        prompt_execution_repo: PromptExecutionRepository,
        file_repo: FileRepository,
    ):
        self.prompt_repo = prompt_repo
        self.prompt_execution_repo = prompt_execution_repo
        self.file_repo = file_repo
        self.prompt_registry = PromptRegistry(prompt_repo, execution_repo=prompt_execution_repo)

    @classmethod
    def from_backend(cls, backend: Backend) -> "PlatformClient":
        return cls(
            prompt_repo=backend.prompt_repo,
            prompt_execution_repo=backend.prompt_execution_repo,
            file_repo=backend.file_repo,
        )
