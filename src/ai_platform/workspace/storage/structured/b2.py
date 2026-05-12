from io import BytesIO
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel
from b2sdk.v2 import InMemoryAccountInfo, B2Api, FileVersion
from b2sdk.v2.exception import FileNotPresent as B2FileNotPresent

from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.structured.base import StoredRecord, RecordReference, RecordRepository

T = TypeVar("T", bound=BaseModel)


class B2RepositoryConfig(BaseModel):
    application_key_id: str
    application_key: str
    bucket_name: str = "app-data"
    prefix: Optional[str] = None


class B2CanonicalRepository(RecordRepository[T], Generic[T]):
    def __init__(self, config: B2RepositoryConfig, *, bucket=None):
        super().__init__(prefix=config.prefix)
        if not hasattr(self, "model_cls"):
            raise TypeError("Repository must define model_cls")
        self.config = config

        if bucket is not None:
            self.bucket = bucket
            return

        # fallback old behavior
        info = InMemoryAccountInfo()
        b2_api: B2Api = B2Api(info)
        b2_api.authorize_account("production", config.application_key_id, config.application_key)
        self.bucket = b2_api.get_bucket_by_name(config.bucket_name)


    def put_canonical(self, logical_name: str, data: T) -> StoredRecord[T]:
        file_name = self._file_name(logical_name)
        payload = data.model_dump_json().encode()

        # Uploading same file_name overwrites (or creates a new version if bucket versioning is enabled)
        fv: FileVersion = self.bucket.upload_bytes(payload, file_name)

        ref = RecordReference(
            id=fv.id_,
            logical_name=logical_name,
            file_name=file_name,
        )
        return StoredRecord(data=data, reference=ref)

    def get_canonical(self, logical_name: str) -> StoredRecord[T]:
        file_name = self._file_name(logical_name)

        try:
            downloaded = self.bucket.download_file_by_name(file_name)
        except B2FileNotPresent:
            raise ObjectNotFound(f"Not found: {file_name}") from None

        buf = BytesIO()
        downloaded.save(buf)
        json_str = buf.getvalue().decode()

        data = self.parse(json_str)

        info = self.bucket.get_file_info_by_name(file_name)
        ref = RecordReference(
            id=info.id_,
            logical_name=logical_name,
            file_name=file_name,
        )
        return StoredRecord(data=data, reference=ref)

    def list_canonicals(self) -> List[str]:
        names: List[str] = []
        
        pfx = (self.config.prefix or "").strip("/")
        if pfx:
            pfx += "/"

        # ✅ old b2sdk: first positional is the folder/prefix (or empty)
        for (fv, _folder) in self.bucket.ls(pfx):
            if not fv.file_name.endswith(".json"):
                continue

            file_name = fv.file_name

            # strip configured repo prefix
            if self.config.prefix:
                repo_prefix = self.config.prefix.rstrip("/") + "/"
                if not file_name.startswith(repo_prefix):
                    continue
                file_name = file_name[len(repo_prefix):]

            logical = file_name[:-5]  # remove ".json"
            names.append(logical)

        return sorted(set(names))


    def list_objects(
        self,
        *,
        prefix: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[StoredRecord[T]]:
        """
        List canonical objects by logical name (optionally within a sub-prefix).
        Minimal, no redesign: uses list_canonicals() + get_canonical().
        """
        names = self.list_canonicals()

        if prefix:
            pfx = prefix.strip("/") + "/"
            names = [n for n in names if n.startswith(pfx)]

        if limit is not None:
            names = names[:limit]

        out: List[StoredRecord[T]] = []
        for logical_name in names:
            out.append(self.get_canonical(logical_name))
        return out
