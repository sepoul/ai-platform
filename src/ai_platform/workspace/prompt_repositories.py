from ai_platform.ai.prompts.models import PromptStore, Prompt, PromptExecutionStore, PromptExecution
from ai_platform.workspace.storage.mixins import SingleStoreMixin
from ai_platform.workspace.storage.structured.b2 import B2CanonicalRepository
from ai_platform.workspace.storage.structured.local import LocalCanonicalRepository

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

class _PromptStoreMixin(SingleStoreMixin[Prompt, PromptStore]):
    model_cls = PromptStore
    missing_label = "Prompt"

    # ---- Protocol surface ----
    # See `ai_platform.workspace.storage.protocols.PromptRepository`.

    def put(self, prompt: Prompt) -> Prompt:
        return self.put_canonical(prompt.id, prompt).data

    def get(self, prompt_id: str) -> Prompt:
        return self.get_canonical(prompt_id).data

    def list(self) -> list[Prompt]:
        return list(self.get_all_items().values())


class _PromptExecutionStoreMixin(SingleStoreMixin[PromptExecution, PromptExecutionStore]):
    model_cls = PromptExecutionStore
    missing_label = "PromptExecution"

    # ---- Protocol surface ----
    # See `ai_platform.workspace.storage.protocols.PromptExecutionRepository`.

    def put(self, execution: PromptExecution) -> PromptExecution:
        return self.put_canonical(execution.id, execution).data

    def list(self, *, limit: int | None = None) -> list[PromptExecution]:
        return list(self.get_all_items(limit=limit).values())

# ---------------------------------------------------------------------------
# NOTE: _JobStoreMixin lives in job_repository.py alongside the domain models
# (JobRecord, JobStatus, JobStore) to avoid circular imports.
# ---------------------------------------------------------------------------
class B2PromptRepository(_PromptStoreMixin, B2CanonicalRepository):
    pass


class B2PromptExecutionRepository(_PromptExecutionStoreMixin, B2CanonicalRepository):
    pass


class LocalPromptRepository(_PromptStoreMixin, LocalCanonicalRepository):
    pass


class LocalPromptExecutionRepository(_PromptExecutionStoreMixin, LocalCanonicalRepository):
    pass
