"""Platform media router — user-supplied byte ingestion (PR-1).

Two endpoints mirror the code-packages upload/download pattern:

- `POST /media` (multipart): a UI/BFF posts user bytes (a voice note, a
  notebook photo). The platform lands them in the storage plane and
  returns a `storage_ref` the caller stamps onto a `storage_ref`-backed
  artifact.
- `GET /media/download?ref=…`: streams the bytes back with their stored
  content-type. This is the URL a blob-backed artifact hydrates to on
  `GET /artifacts/{id}` (`storage_url`).

Bytes traverse the control plane on the way in — the same as uploading a
file to a workspace — but no compute, LLM call, or artifact generation
runs here (see [[media_service]]).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from ai_platform.jobs.media_service import MediaRef, MediaService
from ai_platform.runtime.registry import get_media_service
from ai_platform.workspace.storage.exceptions import ObjectNotFound


router = APIRouter(prefix="/media", tags=["Platform / Media"])


@router.post(
    "",
    response_model=MediaRef,
    status_code=201,
    summary="Upload user bytes; returns a storage_ref",
)
async def upload_media(
    file: UploadFile = File(...),
    content_type: Optional[str] = Form(
        default=None,
        description="Override the part's content-type (e.g. audio/m4a).",
    ),
    service: MediaService = Depends(get_media_service),
):
    data = await file.read()
    # An explicit form field wins; fall back to the multipart part's own
    # declared content-type.
    resolved_ct = content_type or file.content_type
    try:
        return service.put(
            filename=file.filename or "upload",
            content_type=resolved_ct,
            data=data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/download",
    summary="Stream uploaded bytes by storage_ref",
)
def download_media(
    ref: str = Query(..., description="storage_ref returned by POST /media"),
    service: MediaService = Depends(get_media_service),
):
    try:
        data, content_type = service.download(ref)
    except ValueError as e:
        # ref outside the media/ prefix — a misuse, not a missing file.
        raise HTTPException(status_code=400, detail=str(e))
    except ObjectNotFound:
        raise HTTPException(status_code=404, detail=f"Media not found: {ref}")
    filename = ref.rsplit("/", 1)[-1]
    return Response(
        content=data,
        media_type=content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
