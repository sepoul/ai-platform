"""Tests for the CodePackage catalog — wheel upload substrate.

Unlike the JobDefinition / ArtifactType catalogs, CodePackages own a
binary blob (the wheel bytes) in addition to a record. The tests
cover:
1. Repository round-trip (records only).
2. Service: blob + row written together; sha256 verified on download;
   runtime validation; filename validation.
3. API: multipart upload, list, get-by-id, get-by-name, streaming
   download with the original filename in Content-Disposition.
4. Bundle helper: `deploy_code_package(wheel_path, ...)` uploads via
   real multipart through the test client.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_platform.api.routers import code_packages as code_pkgs_router
from ai_platform.bundle import deploy_code_package
from ai_platform.jobs.code_package_service import CodePackageService
from ai_platform.runtime import registry as deps_mod
from ai_platform.workspace.storage.blobs.local import (
    LocalFileRepository,
    LocalFileRepositoryConfig,
)
from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.structured.code_package_repository import (
    CodePackageRecord,
    LocalCodePackageRepository,
)
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig


# A tiny "wheel" — the service only cares about the bytes for sha256
# and storage. Filename validation requires `.whl`.
_WHEEL_BYTES = b"PK\x03\x04fake-wheel-content-for-tests"
_WHEEL_SHA = hashlib.sha256(_WHEEL_BYTES).hexdigest()


@pytest.fixture
def repo(tmp_path: Path) -> LocalCodePackageRepository:
    return LocalCodePackageRepository(
        LocalRepositoryConfig(root_dir=str(tmp_path), prefix="code_packages")
    )


@pytest.fixture
def file_repo(tmp_path: Path) -> LocalFileRepository:
    return LocalFileRepository(
        LocalFileRepositoryConfig(root_dir=str(tmp_path), prefix="files")
    )


@pytest.fixture
def service(
    repo: LocalCodePackageRepository, file_repo: LocalFileRepository
) -> CodePackageService:
    return CodePackageService(repo, file_repo)


def _record_kwargs(name: str = "toy_pkg", version: str = "1.0.0", **overrides) -> dict:
    base = dict(
        id=CodePackageRecord.make_id(name, version),
        name=name,
        version=version,
        runtime_selector="default",
        filename=f"{name}-{version}-py3-none-any.whl",
        blob_id=f"code_packages/{name}-{version}.whl",
        sha256="a" * 64,
        size_bytes=100,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


def test_repo_put_then_get_round_trips(repo: LocalCodePackageRepository):
    record = CodePackageRecord(**_record_kwargs())
    repo.put(record)
    back = repo.get(record.id)
    assert back.name == "toy_pkg"
    assert back.runtime_selector == "default"


def test_repo_put_is_idempotent_on_id(repo: LocalCodePackageRepository):
    repo.put(CodePackageRecord(**_record_kwargs(filename="v1.whl")))
    repo.put(CodePackageRecord(**_record_kwargs(filename="v2.whl")))
    rows = repo.list()
    assert len(rows) == 1
    assert rows[0].filename == "v2.whl"


def test_repo_list_filters_by_runtime(repo: LocalCodePackageRepository):
    repo.put(CodePackageRecord(**_record_kwargs(name="a", runtime_selector="default")))
    repo.put(CodePackageRecord(**_record_kwargs(name="b", runtime_selector="crewai")))
    crewai = repo.list(runtime_selector="crewai")
    assert [r.name for r in crewai] == ["b"]


def test_repo_get_missing_raises(repo: LocalCodePackageRepository):
    with pytest.raises(ObjectNotFound):
        repo.get("ghost@1.0.0")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_service_deploy_writes_blob_and_row(service: CodePackageService):
    record = service.deploy(
        name="toy_pkg",
        version="1.0.0",
        runtime_selector="default",
        filename="toy_pkg-1.0.0-py3-none-any.whl",
        wheel_bytes=_WHEEL_BYTES,
    )
    assert record.id == "toy_pkg@1.0.0"
    assert record.sha256 == _WHEEL_SHA
    assert record.size_bytes == len(_WHEEL_BYTES)

    # Round-trip through the catalog.
    assert service.get("toy_pkg@1.0.0").sha256 == _WHEEL_SHA


def test_service_download_verifies_sha256(service: CodePackageService):
    service.deploy(
        name="toy_pkg",
        version="1.0.0",
        runtime_selector="default",
        filename="toy_pkg-1.0.0-py3-none-any.whl",
        wheel_bytes=_WHEEL_BYTES,
    )
    record, blob = service.download("toy_pkg@1.0.0")
    assert blob == _WHEEL_BYTES
    assert record.filename == "toy_pkg-1.0.0-py3-none-any.whl"


def test_service_download_detects_sha_mismatch(
    service: CodePackageService, repo: LocalCodePackageRepository
):
    """If the catalog row drifts from the blob, download should raise.
    Simulate by writing a record with a wrong sha but a real blob.
    """
    service.deploy(
        name="toy_pkg",
        version="1.0.0",
        runtime_selector="default",
        filename="toy_pkg-1.0.0-py3-none-any.whl",
        wheel_bytes=_WHEEL_BYTES,
    )
    # Tamper: overwrite the row with a fake sha256.
    rec = service.get("toy_pkg@1.0.0")
    bad = rec.model_copy(update={"sha256": "0" * 64})
    repo.put(bad)
    with pytest.raises(ValueError, match="sha256 mismatch"):
        service.download("toy_pkg@1.0.0")


def test_service_rejects_unknown_runtime(service: CodePackageService):
    with pytest.raises(ValueError, match="Unknown runtime_selector"):
        service.deploy(
            name="toy_pkg",
            version="1.0.0",
            runtime_selector="not-a-runtime",
            filename="toy_pkg.whl",
            wheel_bytes=_WHEEL_BYTES,
        )


def test_service_rejects_non_wheel_filename(service: CodePackageService):
    with pytest.raises(ValueError, match=r"Expected a \.whl filename"):
        service.deploy(
            name="toy_pkg",
            version="1.0.0",
            runtime_selector="default",
            filename="toy_pkg.tar.gz",
            wheel_bytes=_WHEEL_BYTES,
        )


def test_service_rejects_empty_name(service: CodePackageService):
    with pytest.raises(ValueError, match="name must be non-empty"):
        service.deploy(
            name="",
            version="1.0.0",
            runtime_selector="default",
            filename="x.whl",
            wheel_bytes=_WHEEL_BYTES,
        )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(service: CodePackageService):
    deps_mod._code_package_service = service
    app = FastAPI()
    app.include_router(code_pkgs_router.router)
    app.dependency_overrides[deps_mod.get_code_package_service] = lambda: service
    return TestClient(app)


def test_post_code_package_creates_row(api_client, service: CodePackageService):
    resp = api_client.post(
        "/code-packages",
        files={"wheel": ("toy_pkg-1.0.0-py3-none-any.whl", _WHEEL_BYTES, "application/octet-stream")},
        data={"name": "toy_pkg", "version": "1.0.0", "runtime_selector": "default"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] == "toy_pkg@1.0.0"
    assert body["sha256"] == _WHEEL_SHA
    assert body["size_bytes"] == len(_WHEEL_BYTES)
    assert len(service.list()) == 1


def test_post_code_package_redeploy_is_idempotent(api_client):
    api_client.post(
        "/code-packages",
        files={"wheel": ("toy_pkg-1.0.0-py3-none-any.whl", b"v1", "application/octet-stream")},
        data={"name": "toy_pkg", "version": "1.0.0", "runtime_selector": "default"},
    )
    resp = api_client.post(
        "/code-packages",
        files={"wheel": ("toy_pkg-1.0.0-py3-none-any.whl", b"v2", "application/octet-stream")},
        data={"name": "toy_pkg", "version": "1.0.0", "runtime_selector": "default"},
    )
    assert resp.status_code == 201
    listing = api_client.get("/code-packages").json()
    assert len(listing) == 1
    assert listing[0]["sha256"] == hashlib.sha256(b"v2").hexdigest()


def test_post_code_package_rejects_unknown_runtime(api_client):
    resp = api_client.post(
        "/code-packages",
        files={"wheel": ("x-1.0.0.whl", _WHEEL_BYTES, "application/octet-stream")},
        data={"name": "x", "version": "1.0.0", "runtime_selector": "bogus"},
    )
    assert resp.status_code == 400
    assert "Unknown runtime_selector" in resp.text


def test_get_code_packages_filters_by_runtime(api_client):
    api_client.post(
        "/code-packages",
        files={"wheel": ("a-1.0.0.whl", b"x", "application/octet-stream")},
        data={"name": "a", "version": "1.0.0", "runtime_selector": "default"},
    )
    api_client.post(
        "/code-packages",
        files={"wheel": ("b-1.0.0.whl", b"y", "application/octet-stream")},
        data={"name": "b", "version": "1.0.0", "runtime_selector": "crewai"},
    )
    crewai = api_client.get("/code-packages?runtime_selector=crewai").json()
    assert [r["name"] for r in crewai] == ["b"]


def test_get_code_package_by_name_returns_latest(api_client):
    import time

    api_client.post(
        "/code-packages",
        files={"wheel": ("toy-1.0.0.whl", b"v1", "application/octet-stream")},
        data={"name": "toy", "version": "1.0.0", "runtime_selector": "default"},
    )
    time.sleep(0.001)
    api_client.post(
        "/code-packages",
        files={"wheel": ("toy-2.0.0.whl", b"v2", "application/octet-stream")},
        data={"name": "toy", "version": "2.0.0", "runtime_selector": "default"},
    )
    resp = api_client.get("/code-packages/by-name/toy")
    assert resp.status_code == 200
    assert resp.json()["version"] == "2.0.0"


def test_get_code_package_by_id_404s(api_client):
    assert api_client.get("/code-packages/ghost@1.0.0").status_code == 404


def test_download_code_package_streams_blob(api_client):
    api_client.post(
        "/code-packages",
        files={"wheel": ("toy-1.0.0.whl", _WHEEL_BYTES, "application/octet-stream")},
        data={"name": "toy", "version": "1.0.0", "runtime_selector": "default"},
    )
    resp = api_client.get("/code-packages/toy@1.0.0/download")
    assert resp.status_code == 200
    assert resp.content == _WHEEL_BYTES
    assert "toy-1.0.0.whl" in resp.headers["content-disposition"]


def test_download_code_package_missing_404s(api_client):
    assert api_client.get("/code-packages/ghost@1.0.0/download").status_code == 404


# ---------------------------------------------------------------------------
# Bundle helper end-to-end via TestClient
# ---------------------------------------------------------------------------


def test_bundle_helper_uploads_wheel(api_client, tmp_path: Path, monkeypatch):
    """deploy_code_package should multipart-POST the file through real
    httpx machinery; we redirect httpx.post to the TestClient.
    """
    wheel_path = tmp_path / "toy-1.0.0-py3-none-any.whl"
    wheel_path.write_bytes(_WHEEL_BYTES)

    def fake_post(url, files=None, data=None, timeout=None):  # noqa: ARG001
        path = url.split("/code-packages", 1)[1] if "/code-packages" in url else url
        # Reshape `files` for httpx -> requests-style for TestClient: the
        # value is (filename, fileobj, content_type) — TestClient accepts
        # the same shape, but we read the bytes first so the closed file
        # doesn't matter.
        fname, fh, ctype = files["wheel"]
        files_for_client = {"wheel": (fname, fh.read(), ctype)}
        resp = api_client.post(
            f"/code-packages{path}", files=files_for_client, data=data
        )

        class _R:
            status_code = resp.status_code

            def raise_for_status(self):
                resp.raise_for_status()

            def json(self):
                return resp.json()

        return _R()

    import ai_platform.bundle as bundle

    monkeypatch.setattr(bundle.httpx, "post", fake_post)

    record = deploy_code_package(
        wheel_path,
        name="toy_pkg",
        version="1.0.0",
        runtime_selector="default",
        api_url="http://fake",
    )
    assert record.id == "toy_pkg@1.0.0"
    assert record.sha256 == _WHEEL_SHA
