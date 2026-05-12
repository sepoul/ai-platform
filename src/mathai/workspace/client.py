from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.workspace.client import PlatformClient
from ai_platform.workspace.storage.backends import make_backend
from ai_platform.workspace.storage.exceptions import ObjectNotFound
from mathai.math_qa.artifacts import MATH_QA_ARTIFACTS
from mathai.workspace.artifacts.service import MathArtifactService

load_dotenv()


class ReadOnlyWorkspace(BaseModel):
    artifact_ids: Optional[list[str]] = None


class MathWorkspaceClient:
    def __init__(
        self,
        artifact_service: MathArtifactService,
        platform_client: PlatformClient,
    ):
        self.artifact_service = artifact_service
        self.platform_client = platform_client

    @property
    def artifact_store(self) -> ArtifactService:
        return self.artifact_service.artifact_store

    def get_workspace(self) -> ReadOnlyWorkspace:
        ids: Optional[list[str]] = None
        try:
            ids = self.artifact_service.list_artifact_ids()
        except ObjectNotFound:
            pass
        return ReadOnlyWorkspace(artifact_ids=ids)

    @classmethod
    def from_artifact_service(
        cls,
        artifact_service: ArtifactService,
        platform_client: PlatformClient,
    ) -> "MathWorkspaceClient":
        """Wraps the shared platform `ArtifactService` plus the platform
        file repo into a math facade. Domains register their artifact
        types on the shared service (see `register_domains`), so the
        math hydrator finds them when looking up `MATH_QA_ARTIFACTS`
        types by id.
        """
        artifact_api = MathArtifactService(
            artifact_store=artifact_service,
            file_repo=platform_client.file_repo,
        )
        return cls(artifact_service=artifact_api, platform_client=platform_client)

    @classmethod
    def create(cls, backend: str = "auto", **kwargs) -> "MathWorkspaceClient":
        """Standalone construction for scripts/tests that don't go
        through the platform bootstrap. Builds its own ArtifactService
        with the math registry.
        """
        b = make_backend(backend, root_dir=kwargs.get("root_dir"))
        platform_client = PlatformClient.from_backend(b)
        artifact_service = ArtifactService(b.artifact_repo, registry=MATH_QA_ARTIFACTS)
        return cls.from_artifact_service(artifact_service, platform_client)
