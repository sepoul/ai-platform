"""Supabase Storage backend for blob files.

Mirrors `LocalFileRepository` / `B2FileRepository` conventions:
file bytes live under the configured prefix; custom metadata is
stored as a sidecar `<filename>.__meta__.json` object next to the
file (same pattern as the local backend — Supabase Storage's native
metadata story is uneven across API versions, sidecars keep us
predictable).

Authenticates with the modern `sb_secret_*` key, which replaces the
legacy JWT-format `service_role` key. RLS-bypassing — keep
server-side only.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional
from uuid import uuid4

import httpx
from pydantic import BaseModel

from ai_platform.workspace.storage.blobs.base import (
    FileReference,
    FileRepository,
    PutFilePayload,
)
from ai_platform.workspace.storage.exceptions import ObjectNotFound

_META_SUFFIX = ".__meta__.json"


class SupabaseFileRepositoryConfig(BaseModel):
    url: str                # https://<project-ref>.supabase.co
    secret_key: str         # sb_secret_...
    bucket_name: str = "app-data"
    prefix: Optional[str] = None
    timeout: float = 30.0


class SupabaseFileRepository(FileRepository):
    def __init__(self, config: SupabaseFileRepositoryConfig):
        self.config = config
        self._base = config.url.rstrip("/") + "/storage/v1"
        self._client = httpx.Client(
            timeout=config.timeout,
            headers={
                "Authorization": f"Bearer {config.secret_key}",
                "apikey": config.secret_key,
            },
        )

    # ------------------------------------------------------------------
    # path helpers
    # ------------------------------------------------------------------

    def _file_name(self, logical_name: str) -> str:
        return f"{self.config.prefix}/{logical_name}" if self.config.prefix else logical_name

    def _logical_name(self, file_name: str) -> str:
        if self.config.prefix and file_name.startswith(f"{self.config.prefix}/"):
            return file_name[len(self.config.prefix) + 1:]
        return file_name

    def _object_url(self, file_name: str) -> str:
        return f"{self._base}/object/{self.config.bucket_name}/{file_name}"

    # ------------------------------------------------------------------
    # low-level transport
    # ------------------------------------------------------------------

    def _upload(self, file_name: str, body: bytes, content_type: Optional[str]) -> None:
        resp = self._client.post(
            self._object_url(file_name),
            content=body,
            headers={
                "Content-Type": content_type or "application/octet-stream",
                "x-upsert": "true",
            },
        )
        resp.raise_for_status()

    def _download(self, file_name: str) -> bytes:
        resp = self._client.get(self._object_url(file_name))
        if resp.is_client_error:
            # Supabase Storage returns either 404 or 400 for missing
            # objects depending on bucket type, with `error: "not_found"`
            # in the JSON body either way.
            try:
                body = resp.json()
            except ValueError:
                body = {}
            if body.get("error") == "not_found" or body.get("statusCode") in ("404", 404):
                raise ObjectNotFound(f"File not found: {file_name}")
        resp.raise_for_status()
        return resp.content

    # ------------------------------------------------------------------
    # bucket lifecycle (helper, not part of FileRepository)
    # ------------------------------------------------------------------

    def ensure_bucket(self, public: bool = False) -> None:
        """Create the configured bucket if missing. Idempotent."""
        resp = self._client.post(
            f"{self._base}/bucket",
            json={
                "id": self.config.bucket_name,
                "name": self.config.bucket_name,
                "public": public,
            },
        )
        if resp.status_code in (200, 201) or resp.status_code == 409:
            return
        # 400 with "already exists" is what Supabase actually returns.
        if resp.status_code == 400 and "already exists" in resp.text.lower():
            return
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # FileRepository surface
    # ------------------------------------------------------------------

    def put_canonical_file(self, payload: PutFilePayload) -> FileReference:
        file_name = self._file_name(payload.logical_name)
        self._upload(file_name, payload.bytes_data, payload.content_type)

        meta = dict(payload.metadata) if payload.metadata else {}
        if payload.content_type:
            meta["__content_type__"] = payload.content_type
        self._upload(
            file_name + _META_SUFFIX,
            json.dumps(meta).encode("utf-8"),
            "application/json",
        )

        return FileReference(
            id=uuid4().hex,
            logical_name=payload.logical_name,
            file_name=file_name,
            content_type=payload.content_type,
        )

    def get_canonical_file_bytes(self, logical_name: str) -> bytes:
        return self._download(self._file_name(logical_name))

    def get_canonoical_file_metadata(self, logical_name: str) -> Dict[str, str]:
        try:
            raw = self._download(self._file_name(logical_name) + _META_SUFFIX)
        except ObjectNotFound:
            raise ObjectNotFound(f"Metadata not found for: {logical_name}") from None
        meta = json.loads(raw.decode("utf-8"))
        return {k: v for k, v in meta.items() if not k.startswith("__")}

    def list_canonical_files(
        self, dir_path: str, metadata: Dict[str, Any] = None
    ) -> Dict[str, FileReference]:
        prefix_parts: list[str] = []
        if self.config.prefix:
            prefix_parts.append(self.config.prefix.strip("/"))
        if dir_path:
            prefix_parts.append(dir_path.strip("/"))
        prefix = "/".join(prefix_parts) + "/" if prefix_parts else ""

        resp = self._client.post(
            f"{self._base}/object/list/{self.config.bucket_name}",
            json={"prefix": prefix, "limit": 1000, "offset": 0},
        )
        resp.raise_for_status()
        items = resp.json()

        files: Dict[str, FileReference] = {}
        for it in items:
            entry = it.get("name", "")
            if not entry or it.get("id") is None:
                # Folder placeholder — Supabase returns `id: None` for these.
                continue
            full_name = f"{prefix}{entry}" if prefix else entry
            if full_name.endswith(_META_SUFFIX):
                continue
            logical = self._logical_name(full_name)
            if metadata:
                try:
                    sidecar = self.get_canonoical_file_metadata(logical)
                except ObjectNotFound:
                    continue
                if not all(sidecar.get(k) == v for k, v in metadata.items()):
                    continue
            files[logical] = FileReference(
                id=uuid4().hex,
                logical_name=logical,
                file_name=full_name,
            )
        return files
