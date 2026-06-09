"""MediaService — user-supplied bytes entering the platform (PR-1).

A path for voice notes, notebook photos, and other user bytes to land
in the storage plane and be carried by a `storage_ref`-backed artifact.
Mirrors [[code_package_service]]: the bytes go through the
`FileRepository` (under the `media/` prefix) and the caller gets back a
`storage_ref` handle. Unlike code packages there is *no catalog row* —
the ref is the only handle, and it lives on the artifact that references
the blob.

Boundary (platform-requirements.md PR-1): the platform only carries the
bytes and the ref. Bytes traverse the control plane on the way in — the
same as uploading a file to a workspace — but no compute, LLM call, or
artifact generation runs here. Transcription (ASR), OCR, and vision are
domain tools that read the bytes via the ref off the control plane.
"""
from __future__ import annotations

import re
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel

from ai_platform.workspace.storage.blobs.base import FileRepository, PutFilePayload


_BLOB_PREFIX = "media"
# Conservative whitelist — anything else collapses to "_" so the
# sanitized name can never introduce a path separator or escape the
# `media/` prefix (defense-in-depth; the local repo also guards
# traversal in `_resolve_path`).
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
# Stored alongside the blob so a download can echo the original
# content-type back to the client (FileRepository hides its internal
# `__content_type__` sidecar key behind `__`, so we keep our own).
_CONTENT_TYPE_KEY = "content_type"


class MediaRef(BaseModel):
    """Handle for an uploaded blob — what `POST /media` returns and what
    a domain stamps onto a `storage_ref`-backed `BaseArtifact`.
    """

    storage_ref: str            # FileRepository logical_name, e.g. "media/<uuid>/notes.jpg"
    filename: str               # sanitized name (last segment of storage_ref)
    content_type: Optional[str] = None
    byte_size: int


def _sanitize_filename(filename: str) -> str:
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE.sub("_", base).strip("._")
    return cleaned or "upload"


class MediaService:
    def __init__(self, file_repo: FileRepository):
        self.file_repo = file_repo

    def put(
        self,
        *,
        filename: str,
        content_type: Optional[str],
        data: bytes,
    ) -> MediaRef:
        """Store bytes and return a ref. The `<uuid>/` segment makes the
        ref unique; the sanitized original name is preserved as the last
        segment so a later download keeps a sensible filename.
        """
        if not data:
            raise ValueError("Refusing to store an empty upload")
        safe = _sanitize_filename(filename)
        storage_ref = f"{_BLOB_PREFIX}/{uuid4().hex}/{safe}"

        metadata: dict[str, str] = {}
        if content_type:
            metadata[_CONTENT_TYPE_KEY] = content_type

        self.file_repo.put_canonical_file(
            PutFilePayload(
                logical_name=storage_ref,
                bytes_data=data,
                content_type=content_type,
                metadata=metadata,
            )
        )
        return MediaRef(
            storage_ref=storage_ref,
            filename=safe,
            content_type=content_type,
            byte_size=len(data),
        )

    def download(self, storage_ref: str) -> tuple[bytes, Optional[str]]:
        """Fetch the bytes for a `storage_ref` plus its stored
        content-type. Scoped to the `media/` prefix so the route can't be
        turned into an arbitrary blob reader (wheels, prompt blobs, …).
        Raises `ObjectNotFound` when the ref doesn't resolve.
        """
        from ai_platform.workspace.storage.exceptions import ObjectNotFound

        if not storage_ref.startswith(f"{_BLOB_PREFIX}/"):
            raise ValueError(
                f"storage_ref must be under {_BLOB_PREFIX}/: {storage_ref!r}"
            )
        data = self.file_repo.get_canonical_file_bytes(storage_ref)
        content_type: Optional[str] = None
        try:
            meta = self.file_repo.get_canonoical_file_metadata(storage_ref)
            content_type = meta.get(_CONTENT_TYPE_KEY) or None
        except ObjectNotFound:
            # Bytes exist without a metadata sidecar — fall back to no
            # declared content-type rather than 404ing the download.
            pass
        return data, content_type
