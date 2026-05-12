from pathlib import Path
from typing import Generic, List, Optional, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.structured.base import (
    StoredRecord,
    RecordReference,
    RecordRepository,
)

T = TypeVar("T", bound=BaseModel)


class LocalRepositoryConfig(BaseModel):
    root_dir: str
    prefix: Optional[str] = None


class LocalCanonicalRepository(RecordRepository[T], Generic[T]):
    def __init__(self, config: LocalRepositoryConfig):
        super().__init__(prefix=config.prefix)
        if not hasattr(self, "model_cls"):
            raise TypeError("Repository must define model_cls")
        self.config = config
        self._base_path = Path(config.root_dir)
        if config.prefix:
            self._base_path = self._base_path / config.prefix
        self._base_path.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, logical_name: str) -> Path:
        resolved = (self._base_path / f"{logical_name}.json").resolve()
        if not resolved.is_relative_to(self._base_path.resolve()):
            raise ValueError(f"Path traversal detected: {logical_name}")
        return resolved

    def put_canonical(self, logical_name: str, data: T) -> StoredRecord[T]:
        file_path = self._resolve_path(logical_name)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = data.model_dump_json()
        file_path.write_text(payload, encoding="utf-8")

        file_name = self._file_name(logical_name)
        ref = RecordReference(
            id=uuid4().hex,
            logical_name=logical_name,
            file_name=file_name,
        )
        return StoredRecord(data=data, reference=ref)

    def get_canonical(self, logical_name: str) -> StoredRecord[T]:
        file_path = self._resolve_path(logical_name)
        if not file_path.exists():
            raise ObjectNotFound(f"File not found: {file_path}")

        json_str = file_path.read_text(encoding="utf-8")
        data = self.parse(json_str)

        file_name = self._file_name(logical_name)
        ref = RecordReference(
            id=uuid4().hex,
            logical_name=logical_name,
            file_name=file_name,
        )
        return StoredRecord(data=data, reference=ref)

    def list_canonicals(self) -> List[str]:
        if not self._base_path.exists():
            return []
        names = [p.stem for p in self._base_path.glob("*.json")]
        return sorted(names)

    def list_objects(
        self,
        *,
        prefix: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[StoredRecord[T]]:
        names = self.list_canonicals()
        if prefix:
            pfx = prefix.strip("/") + "/"
            names = [n for n in names if n.startswith(pfx)]
        if limit is not None:
            names = names[:limit]
        return [self.get_canonical(n) for n in names]
