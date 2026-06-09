"""Tests for PR-1 — media ingestion + blob-backed artifacts.

Three cuts, mirroring `test_code_package_catalog.py`:

1. **MediaService** — bytes land in the FileRepository under `media/`;
   `put` returns a `storage_ref` + content_type + byte_size; `download`
   round-trips bytes + content_type; the prefix scope and empty-upload
   guards hold.
2. **Media router** — `POST /media` multipart upload, `GET
   /media/download` streaming with content-type, 404 on a missing ref,
   400 on a ref outside the `media/` prefix.
3. **Blob-backed artifact** — `BaseArtifact` carries `storage_ref` /
   content_type / byte_size; `storage_url` is transient (never
   persisted) and is hydrated on `GET /artifacts/{id}`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_platform.api.routers import media as media_router
from ai_platform.api.routers.artifacts import make_artifacts_router
from ai_platform.jobs.artifact import BaseArtifact
from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.jobs.media_service import MediaService
from ai_platform.runtime import registry as deps_mod
from ai_platform.workspace.storage.blobs.local import (
    LocalFileRepository,
    LocalFileRepositoryConfig,
)
from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.structured.artifact_repository import (
    LocalArtifactRepository,
)
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig


_IMG_BYTES = b"\xff\xd8\xff\xe0notebook-photo-bytes"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def file_repo(tmp_path: Path) -> LocalFileRepository:
    return LocalFileRepository(
        LocalFileRepositoryConfig(root_dir=str(tmp_path), prefix="files")
    )


@pytest.fixture
def service(file_repo: LocalFileRepository) -> MediaService:
    return MediaService(file_repo)


# ---------------------------------------------------------------------------
# MediaService
# ---------------------------------------------------------------------------


def test_put_stores_bytes_and_returns_ref(service: MediaService):
    ref = service.put(filename="notes.jpg", content_type="image/jpeg", data=_IMG_BYTES)
    assert ref.storage_ref.startswith("media/")
    assert ref.storage_ref.endswith("/notes.jpg")
    assert ref.filename == "notes.jpg"
    assert ref.content_type == "image/jpeg"
    assert ref.byte_size == len(_IMG_BYTES)


def test_put_then_download_round_trips(service: MediaService):
    ref = service.put(filename="voice.m4a", content_type="audio/m4a", data=_IMG_BYTES)
    data, content_type = service.download(ref.storage_ref)
    assert data == _IMG_BYTES
    assert content_type == "audio/m4a"


def test_put_is_unique_per_upload(service: MediaService):
    a = service.put(filename="x.jpg", content_type="image/jpeg", data=b"a")
    b = service.put(filename="x.jpg", content_type="image/jpeg", data=b"b")
    # Same filename, distinct refs (uuid segment) — no clobber.
    assert a.storage_ref != b.storage_ref
    assert service.download(a.storage_ref)[0] == b"a"
    assert service.download(b.storage_ref)[0] == b"b"


def test_put_sanitizes_path_separators_in_filename(service: MediaService):
    ref = service.put(
        filename="../../etc/passwd", content_type=None, data=_IMG_BYTES
    )
    # Directory components are stripped; the ref stays under media/.
    assert ref.storage_ref.startswith("media/")
    assert "/passwd" in ref.storage_ref
    assert ".." not in ref.storage_ref
    # And the bytes are retrievable at the sanitized ref.
    assert service.download(ref.storage_ref)[0] == _IMG_BYTES


def test_put_rejects_empty_upload(service: MediaService):
    with pytest.raises(ValueError, match="empty upload"):
        service.put(filename="empty.bin", content_type=None, data=b"")


def test_download_missing_raises(service: MediaService):
    with pytest.raises(ObjectNotFound):
        service.download("media/does-not-exist/ghost.jpg")


def test_download_rejects_ref_outside_media_prefix(service: MediaService):
    with pytest.raises(ValueError, match="must be under media/"):
        service.download("code_packages/toy-1.0.0.whl")


def test_download_without_content_type_falls_back_to_none(service: MediaService):
    ref = service.put(filename="raw.bin", content_type=None, data=_IMG_BYTES)
    data, content_type = service.download(ref.storage_ref)
    assert data == _IMG_BYTES
    assert content_type is None


# ---------------------------------------------------------------------------
# Media router
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(service: MediaService):
    deps_mod._media_service = service
    app = FastAPI()
    app.include_router(media_router.router)
    app.dependency_overrides[deps_mod.get_media_service] = lambda: service
    return TestClient(app)


def test_post_media_returns_ref(api_client):
    resp = api_client.post(
        "/media",
        files={"file": ("notes.jpg", _IMG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["storage_ref"].startswith("media/")
    assert body["filename"] == "notes.jpg"
    assert body["content_type"] == "image/jpeg"
    assert body["byte_size"] == len(_IMG_BYTES)


def test_post_media_form_content_type_overrides_part(api_client):
    resp = api_client.post(
        "/media",
        files={"file": ("clip.bin", _IMG_BYTES, "application/octet-stream")},
        data={"content_type": "audio/m4a"},
    )
    assert resp.status_code == 201
    assert resp.json()["content_type"] == "audio/m4a"


def test_post_then_download_via_route(api_client):
    ref = api_client.post(
        "/media",
        files={"file": ("notes.jpg", _IMG_BYTES, "image/jpeg")},
    ).json()["storage_ref"]
    resp = api_client.get("/media/download", params={"ref": ref})
    assert resp.status_code == 200
    assert resp.content == _IMG_BYTES
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert "notes.jpg" in resp.headers["content-disposition"]


def test_download_missing_404s(api_client):
    resp = api_client.get("/media/download", params={"ref": "media/ghost/x.jpg"})
    assert resp.status_code == 404


def test_download_outside_prefix_400s(api_client):
    resp = api_client.get(
        "/media/download", params={"ref": "code_packages/toy.whl"}
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Blob-backed artifact: storage_ref persists, storage_url is transient
# ---------------------------------------------------------------------------


class _NoteArtifact(BaseArtifact):
    artifact_type: Literal["note"] = "note"
    title: str = ""


@pytest.fixture
def artifact_service(tmp_path: Path) -> ArtifactService:
    repo = LocalArtifactRepository(
        LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts")
    )
    return ArtifactService(repo, registry={"note": _NoteArtifact})


def test_storage_ref_fields_round_trip(artifact_service: ArtifactService):
    art = _NoteArtifact(
        title="scan",
        storage_ref="media/abc/scan.jpg",
        content_type="image/jpeg",
        byte_size=123,
    )
    artifact_service.put(art)
    back = artifact_service.get(art.artifact_id)
    assert back.storage_ref == "media/abc/scan.jpg"
    assert back.content_type == "image/jpeg"
    assert back.byte_size == 123


def test_storage_url_is_not_persisted(artifact_service: ArtifactService):
    art = _NoteArtifact(storage_ref="media/abc/scan.jpg")
    # Even if something set storage_url before put, it must not survive.
    art.storage_url = "/media/download?ref=should-not-persist"
    artifact_service.put(art)
    back = artifact_service.get(art.artifact_id)
    assert back.storage_url is None


def test_get_artifact_hydrates_storage_url(artifact_service: ArtifactService):
    art = _NoteArtifact(storage_ref="media/abc/scan.jpg", content_type="image/jpeg")
    artifact_service.put(art)

    app = FastAPI()
    app.include_router(make_artifacts_router([_NoteArtifact]))
    app.dependency_overrides[deps_mod.get_artifact_service] = lambda: artifact_service
    client = TestClient(app)

    resp = client.get(f"/artifacts/{art.artifact_id}")
    assert resp.status_code == 200
    body = resp.json()
    # storage_ref carries `/` — it's percent-encoded into the query value.
    assert body["storage_url"] == "/media/download?ref=media%2Fabc%2Fscan.jpg"
    assert body["storage_ref"] == "media/abc/scan.jpg"


def test_get_artifact_without_storage_ref_has_null_url(
    artifact_service: ArtifactService,
):
    art = _NoteArtifact(title="json-only")
    artifact_service.put(art)

    app = FastAPI()
    app.include_router(make_artifacts_router([_NoteArtifact]))
    app.dependency_overrides[deps_mod.get_artifact_service] = lambda: artifact_service
    client = TestClient(app)

    resp = client.get(f"/artifacts/{art.artifact_id}")
    assert resp.status_code == 200
    assert resp.json()["storage_url"] is None


# ---------------------------------------------------------------------------
# Demo domain UAT loop: a submitted storage_ref lands on the artifact
# ---------------------------------------------------------------------------


def test_demo_persist_stamps_storage_ref(tmp_path: Path):
    """The demo job threads an optional storage_ref from input → state →
    persisted artifact, so the full PR-1 ingest loop is exercisable out
    of the box (upload → demo job → blob-backed artifact → hydrated URL).
    """
    from aiplatform_demo.artifacts import DEMO_ARTIFACTS
    from aiplatform_demo.execution import build_demo_execution
    from aiplatform_demo.state import DemoState
    from unittest.mock import MagicMock

    repo = LocalArtifactRepository(
        LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts")
    )
    artifact_api = ArtifactService(repo, registry=dict(DEMO_ARTIFACTS))
    execution = build_demo_execution(artifact_api, platform_client=MagicMock())

    # deps_factory carries the ref off the submit payload.
    deps = execution.deps_factory(
        {"message": "hi", "storage_ref": "media/abc/scan.jpg", "content_type": "image/jpeg", "byte_size": 7}
    )
    assert deps.storage_ref == "media/abc/scan.jpg"

    # persist stamps it onto the produced artifact.
    state = DemoState(
        message="hi",
        echoed="HI",
        storage_ref="media/abc/scan.jpg",
        content_type="image/jpeg",
        byte_size=7,
    )
    ids = execution.persistence.on_complete("job-1", state)
    assert len(ids) == 1
    stored = artifact_api.get(ids[0])
    assert stored.storage_ref == "media/abc/scan.jpg"
    assert stored.content_type == "image/jpeg"
    assert stored.byte_size == 7
