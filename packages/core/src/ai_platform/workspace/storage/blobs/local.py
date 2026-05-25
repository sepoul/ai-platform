import json
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel

from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.blobs.base import (
    FileReference,
    FileRepository,
    PutFilePayload,
)


class LocalFileRepositoryConfig(BaseModel):
    root_dir: str
    prefix: Optional[str] = None


class LocalFileRepository(FileRepository):
    def __init__(self, config: LocalFileRepositoryConfig):
        self.config = config
        self._base_path = Path(config.root_dir)
        if config.prefix:
            self._base_path = self._base_path / config.prefix
        self._base_path.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, logical_name: str) -> Path:
        resolved = (self._base_path / logical_name).resolve()
        if not resolved.is_relative_to(self._base_path.resolve()):
            raise ValueError(f"Path traversal detected: {logical_name}")
        return resolved

    def _metadata_path(self, logical_name: str) -> Path:
        return self._resolve_path(logical_name).with_suffix(
            self._resolve_path(logical_name).suffix + ".__meta__.json"
        )

    def _metadata_path_for(self, file_path: Path) -> Path:
        return file_path.parent / f"{file_path.name}.__meta__.json"

    def put_canonical_file(self, payload: PutFilePayload) -> FileReference:
        file_path = self._resolve_path(payload.logical_name)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(payload.bytes_data)

        # Store metadata as sidecar JSON
        meta = dict(payload.metadata) if payload.metadata else {}
        if payload.content_type:
            meta["__content_type__"] = payload.content_type
        meta_path = self._metadata_path_for(file_path)
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        file_name = (
            f"{self.config.prefix}/{payload.logical_name}"
            if self.config.prefix
            else payload.logical_name
        )
        return FileReference(
            id=uuid4().hex,
            logical_name=payload.logical_name,
            file_name=file_name,
            content_type=payload.content_type,
        )

    def get_canonical_file_bytes(self, logical_name: str) -> bytes:
        file_path = self._resolve_path(logical_name)
        if not file_path.exists():
            raise ObjectNotFound(f"File not found: {file_path}")
        return file_path.read_bytes()

    def get_canonoical_file_metadata(self, logical_name: str) -> Dict[str, str]:
        file_path = self._resolve_path(logical_name)
        meta_path = self._metadata_path_for(file_path)
        if not meta_path.exists():
            raise ObjectNotFound(f"Metadata not found for: {logical_name}")
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        # Strip internal keys (prefixed with __)
        return {k: v for k, v in raw.items() if not k.startswith("__")}

    def list_canonical_files(
        self, dir_path: str, metadata: Dict[str, Any] = None
    ) -> Dict[str, FileReference]:
        search_path = self._base_path / dir_path
        if not search_path.exists():
            return {}
        files = {}
        for p in search_path.iterdir():
            if p.is_file() and ".__meta__.json" not in p.name:
                logical_name = str(p.relative_to(self._base_path))
                if metadata:
                    meta_path = self._metadata_path_for(p)
                    if meta_path.exists():
                        file_meta = json.loads(meta_path.read_text())
                        clean_meta = {
                            k: v
                            for k, v in file_meta.items()
                            if not k.startswith("__")
                        }
                        if not all(
                            clean_meta.get(k) == v for k, v in metadata.items()
                        ):
                            continue
                    else:
                        continue
                file_name = (
                    f"{self.config.prefix}/{logical_name}"
                    if self.config.prefix
                    else logical_name
                )
                files[logical_name] = FileReference(
                    id=uuid4().hex,
                    logical_name=logical_name,
                    file_name=file_name,
                )
        return files
