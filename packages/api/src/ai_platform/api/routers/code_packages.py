"""Platform code-packages router — wheel upload + download.

Three endpoints:

- `POST /code-packages` (multipart): a friend's bundle deploy posts a
  wheel, its name+version+runtime, and the platform stores the bytes
  + records the catalog row. Idempotent on `(name, version)`.
- `GET /code-packages[?runtime_selector=…]`: list the catalog.
- `GET /code-packages/{id}/download`: streams the wheel bytes back,
  verified against the recorded sha256. The future worker install
  path uses this.

The wheel bytes go through `FileRepository` (via `CodePackageService`),
not through the catalog row. The row is the metadata pointer.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ai_platform.jobs.code_package_service import CodePackageService
from ai_platform.runtime.registry import get_code_package_service
from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.structured.code_package_repository import (
    CodePackageRecord,
)


router = APIRouter()


@router.post(
    "/code-packages",
    response_model=CodePackageRecord,
    status_code=201,
    summary="Upload a wheel (idempotent on name+version)",
)
async def upload_code_package(
    name: str = Form(...),
    version: str = Form("1.0.0"),
    runtime_selector: str = Form(...),
    wheel: UploadFile = File(...),
    service: CodePackageService = Depends(get_code_package_service),
):
    wheel_bytes = await wheel.read()
    filename = wheel.filename or f"{name}-{version}.whl"
    try:
        return service.deploy(
            name=name,
            version=version,
            runtime_selector=runtime_selector,
            filename=filename,
            wheel_bytes=wheel_bytes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/code-packages",
    response_model=list[CodePackageRecord],
    summary="List deployed CodePackages",
)
def list_code_packages(
    runtime_selector: str | None = None,
    service: CodePackageService = Depends(get_code_package_service),
):
    return service.list(runtime_selector=runtime_selector)


@router.get(
    "/code-packages/by-name/{name}",
    response_model=CodePackageRecord,
    summary="Latest-deployed version of a named CodePackage",
)
def get_code_package_by_name(
    name: str,
    service: CodePackageService = Depends(get_code_package_service),
):
    try:
        return service.get_by_name(name)
    except ObjectNotFound:
        raise HTTPException(status_code=404, detail=f"No CodePackage named {name!r}")


@router.get(
    "/code-packages/{package_id}",
    response_model=CodePackageRecord,
    summary="Get a specific CodePackage by id",
)
def get_code_package(
    package_id: str,
    service: CodePackageService = Depends(get_code_package_service),
):
    try:
        return service.get(package_id)
    except ObjectNotFound:
        raise HTTPException(status_code=404, detail=f"CodePackage not found: {package_id}")


@router.get(
    "/code-packages/{package_id}/download",
    summary="Download the wheel bytes (sha256-verified)",
)
def download_code_package(
    package_id: str,
    service: CodePackageService = Depends(get_code_package_service),
):
    try:
        record, wheel_bytes = service.download(package_id)
    except ObjectNotFound:
        raise HTTPException(status_code=404, detail=f"CodePackage not found: {package_id}")
    return Response(
        content=wheel_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{record.filename}"'},
    )
