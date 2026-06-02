"""Storage backend factory.

A `Backend` bundles every Protocol-conformant repository the workspace
needs (file, jobs, artifacts, prompts, prompt executions). Adding a new
backend means adding one class here and one branch in `make_backend`;
`PlatformClient` and `bootstrap_workspace` stay backend-agnostic.

Resolution: `BACKEND` env var, defaulting to `b2` when `B2_KEY_ID` is
set, else `local`. See `docs/project/supabase_intro.md` for the
in-flight Supabase backend.
"""
from __future__ import annotations

import os
from typing import Protocol

from dotenv import load_dotenv

from ai_platform.workspace.prompt_repositories import (
    B2PromptExecutionRepository,
    B2PromptRepository,
    LocalPromptExecutionRepository,
    LocalPromptRepository,
)
from ai_platform.workspace.storage.b2_context import make_b2_context
from ai_platform.workspace.storage.blobs.b2 import B2FileRepository, B2FileRepositoryConfig
from ai_platform.workspace.storage.blobs.local import (
    LocalFileRepository,
    LocalFileRepositoryConfig,
)
from ai_platform.workspace.storage.blobs.supabase import (
    SupabaseFileRepository,
    SupabaseFileRepositoryConfig,
)
from ai_platform.workspace.storage.protocols import (
    ArtifactRepository,
    ArtifactTypeRepository,
    JobDefinitionRepository,
    JobRepository,
    PromptExecutionRepository,
    PromptRepository,
)
from ai_platform.workspace.storage.blobs.base import FileRepository
from ai_platform.workspace.storage.structured.artifact_repository import (
    B2ArtifactRepository,
    LocalArtifactRepository,
)
from ai_platform.workspace.storage.structured.artifact_type_repository import (
    B2ArtifactTypeRepository,
    LocalArtifactTypeRepository,
)
from ai_platform.workspace.storage.structured.b2 import B2RepositoryConfig
from ai_platform.workspace.storage.structured.job_definition_repository import (
    B2JobDefinitionRepository,
    LocalJobDefinitionRepository,
)
from ai_platform.workspace.storage.structured.job_repository import (
    B2JobRepository,
    LocalJobRepository,
)
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig
from ai_platform.workspace.storage.structured.supabase import (
    SupabaseArtifactRepository,
    SupabaseArtifactTypeRepository,
    SupabaseJobDefinitionRepository,
    SupabaseJobRepository,
    SupabasePromptExecutionRepository,
    SupabasePromptRepository,
    make_pool,
)

load_dotenv()


class Backend(Protocol):
    name: str
    file_repo: FileRepository
    job_repo: JobRepository
    artifact_repo: ArtifactRepository
    prompt_repo: PromptRepository
    prompt_execution_repo: PromptExecutionRepository
    job_definition_repo: JobDefinitionRepository
    artifact_type_repo: ArtifactTypeRepository


class LocalBackend:
    name = "local"

    def __init__(self, root_dir: str):
        self.root_dir = root_dir

        def cfg(prefix: str) -> LocalRepositoryConfig:
            return LocalRepositoryConfig(root_dir=root_dir, prefix=prefix)

        self.file_repo: FileRepository = LocalFileRepository(
            LocalFileRepositoryConfig(root_dir=root_dir, prefix="files")
        )
        self.job_repo: JobRepository = LocalJobRepository(cfg("jobs"))
        self.artifact_repo: ArtifactRepository = LocalArtifactRepository(cfg("artifacts"))
        self.prompt_repo: PromptRepository = LocalPromptRepository(cfg("prompts"))
        self.prompt_execution_repo: PromptExecutionRepository = LocalPromptExecutionRepository(
            cfg("prompt_executions")
        )
        self.job_definition_repo: JobDefinitionRepository = LocalJobDefinitionRepository(
            cfg("job_definitions")
        )
        self.artifact_type_repo: ArtifactTypeRepository = LocalArtifactTypeRepository(
            cfg("artifact_types")
        )


class B2Backend:
    name = "b2"

    def __init__(self, key_id: str, app_key: str, bucket_name: str):
        self._ctx = make_b2_context(
            application_key_id=key_id,
            application_key=app_key,
            bucket_name=bucket_name,
        )
        bucket = self._ctx.bucket

        def cfg(prefix: str) -> B2RepositoryConfig:
            return B2RepositoryConfig(
                application_key_id=key_id,
                application_key=app_key,
                bucket_name=bucket_name,
                prefix=prefix,
            )

        self.file_repo: FileRepository = B2FileRepository(
            B2FileRepositoryConfig(
                application_key_id=key_id,
                application_key=app_key,
                bucket_name=bucket_name,
                prefix="files",
            ),
            bucket=bucket,
        )
        self.job_repo: JobRepository = B2JobRepository(cfg("jobs"), bucket=bucket)
        self.artifact_repo: ArtifactRepository = B2ArtifactRepository(
            cfg("artifacts"), bucket=bucket
        )
        self.prompt_repo: PromptRepository = B2PromptRepository(cfg("prompts"), bucket=bucket)
        self.prompt_execution_repo: PromptExecutionRepository = B2PromptExecutionRepository(
            cfg("prompt_executions"), bucket=bucket
        )
        self.job_definition_repo: JobDefinitionRepository = B2JobDefinitionRepository(
            cfg("job_definitions"), bucket=bucket
        )
        self.artifact_type_repo: ArtifactTypeRepository = B2ArtifactTypeRepository(
            cfg("artifact_types"), bucket=bucket
        )


class SupabaseBackend:
    name = "supabase"

    def __init__(
        self,
        *,
        url: str,
        secret_key: str,
        bucket_name: str,
        connection_string: str,
    ):
        self._pool = make_pool(connection_string)

        self.file_repo: FileRepository = SupabaseFileRepository(
            SupabaseFileRepositoryConfig(
                url=url,
                secret_key=secret_key,
                bucket_name=bucket_name,
                prefix="files",
            )
        )
        self.job_repo: JobRepository = SupabaseJobRepository(self._pool)
        self.artifact_repo: ArtifactRepository = SupabaseArtifactRepository(self._pool)
        self.prompt_repo: PromptRepository = SupabasePromptRepository(self._pool)
        self.prompt_execution_repo: PromptExecutionRepository = SupabasePromptExecutionRepository(
            self._pool
        )
        self.job_definition_repo: JobDefinitionRepository = SupabaseJobDefinitionRepository(
            self._pool
        )
        self.artifact_type_repo: ArtifactTypeRepository = SupabaseArtifactTypeRepository(
            self._pool
        )


def make_backend(name: str | None = None, *, root_dir: str | None = None) -> Backend:
    """Resolve the active backend from `BACKEND` env (or the explicit
    `name`) and construct it. `root_dir` is honored only by the local
    backend; it falls back to `LOCAL_DATA_DIR`, then `~/.appdata`.
    """
    if name is None or name == "auto":
        name = os.getenv("BACKEND") or ("b2" if os.getenv("B2_KEY_ID") else "local")

    if name == "local":
        resolved_root = (
            root_dir
            or os.getenv("LOCAL_DATA_DIR")
            or os.path.expanduser("~/.appdata")
        )
        return LocalBackend(root_dir=resolved_root)

    if name == "b2":
        return B2Backend(
            key_id=os.getenv("B2_KEY_ID", ""),
            app_key=os.getenv("B2_APP_KEY", ""),
            bucket_name=os.getenv("B2_BUCKET", "app-data"),
        )

    if name == "supabase":
        return SupabaseBackend(
            url=os.environ["SUPABASE_URL"],
            secret_key=os.environ["SUPABASE_SECRET_KEY"],
            bucket_name=os.getenv("SUPABASE_BUCKET", "app-data"),
            connection_string=os.environ["SUPABASE_CONNECTION_STRING"],
        )

    raise ValueError(f"Unknown backend: {name}")
