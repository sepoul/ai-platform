
from io import BytesIO
from typing import Dict, Optional, Any
from pydantic import BaseModel
from b2sdk.v2 import InMemoryAccountInfo, B2Api, FileVersion
from b2sdk.v2.exception import FileNotPresent as B2FileNotPresent

from ai_platform.workspace.storage.blobs.base import FileReference, FileRepository, PutFilePayload
from ai_platform.workspace.storage.exceptions import ObjectNotFound


class B2FileRepositoryConfig(BaseModel):
    application_key_id: str
    application_key: str
    bucket_name: str = "app-data"
    prefix: Optional[str] = None


class B2FileRepository(FileRepository):
    def __init__(self, config: B2FileRepositoryConfig, *, bucket=None):
        self.config = config
        if bucket is not None:
            self.bucket = bucket
            return

        info = InMemoryAccountInfo()
        b2_api = B2Api(info)
        b2_api.authorize_account("production", config.application_key_id, config.application_key)
        self.bucket = b2_api.get_bucket_by_name(config.bucket_name)

    def _file_name(self, logical_name: str) -> str:
        # strongly recommend logical_name includes extension: "hr_export_latest.xlsx"
        return f"{self.config.prefix}/{logical_name}" if self.config.prefix else logical_name
    
    def _logical_name(self, file_name: str) -> str:
        if self.config.prefix and file_name.startswith(f"{self.config.prefix}/"):
            return file_name[len(self.config.prefix) + 1 :]
        return file_name

    def put_canonical_file(self, payload: PutFilePayload) -> FileReference:
        file_name = self._file_name(payload.logical_name)
        fv: FileVersion = self.bucket.upload_bytes(
            payload.bytes_data,
            file_name,
            content_type=payload.content_type,
            file_infos=payload.metadata or None,
        )
        return FileReference(
            id=fv.id_,
            logical_name=payload.logical_name,
            file_name=file_name,
            content_type=payload.content_type,
        )

    def get_canonical_file_bytes(self, logical_name: str) -> bytes:
        file_name = self._file_name(logical_name)
        try:
            downloaded = self.bucket.download_file_by_name(file_name)
        except B2FileNotPresent:
            raise ObjectNotFound(f"File not found: {file_name}") from None
        buf = BytesIO()
        downloaded.save(buf)
        return buf.getvalue()

    def get_canonoical_file_metadata(self, logical_name):
        try:
            return self.bucket.get_file_info_by_name(self._file_name(logical_name)).file_info
        except B2FileNotPresent:
            raise ObjectNotFound(f"Metadata not found: {logical_name}") from None

    def list_canonical_files(self, dir_path: str, metadata: Dict[str, Any] = None) -> Dict[str, FileReference]:
        files = {}
        prefix = f"{self.config.prefix}/" if self.config.prefix else ""
        prefix += dir_path.rstrip("/") + "/"
        for file_version, _ in self.bucket.ls(prefix):
            file_version_: FileVersion = file_version  # type: ignore
            file_info = file_version_.file_info
            if not self.should_include(file_info, metadata):
                continue
            logical_name = self._logical_name(file_version_.file_name)
            files[logical_name] = FileReference(
                id=file_version_.id_,
                logical_name=logical_name,
                file_name=file_version_.file_name,
                content_type=file_version_.content_type,
            )
        return files
    
    @staticmethod
    def should_include(file_info: Dict[str, str], metadata: Dict[str, Any]) -> bool:
        if not metadata:
            return True
        for key, value in metadata.items():
            if key not in file_info or file_info[key] != value:
                return False
        return True
