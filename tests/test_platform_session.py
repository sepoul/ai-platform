"""Tests for the runtime-side PlatformSession.

Three layers:
1. Catalog reads — list/get for each of the three catalogs, with the
   optional filter args round-tripped to the API.
2. submit_job + JobHandle — payload reshaping (dict + BaseJobInput),
   the submit endpoint shape, get_job, refresh, status caching.
3. wait/result/timeout — `time.sleep` patched out for determinism;
   `time.monotonic` driven via a fake clock so the timeout branch is
   reachable without wall-clock delay.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_platform.api.routers import artifact_types as artifact_types_router
from ai_platform.api.routers import code_packages as code_pkgs_router
from ai_platform.api.routers import job_definitions as job_defs_router
from ai_platform.jobs.artifact_type_service import ArtifactTypeService
from ai_platform.jobs.code_package_service import CodePackageService
from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.job_definition_service import JobDefinitionService
from ai_platform.runtime import registry as deps_mod
from ai_platform.session import JobHandle, PlatformSession
from ai_platform.session.session import (
    JobNotFound,
    JobTimeout,
    PlatformSessionError,
)
from ai_platform.workspace.storage.blobs.local import (
    LocalFileRepository,
    LocalFileRepositoryConfig,
)
from ai_platform.workspace.storage.structured.artifact_type_repository import (
    ArtifactTypeRecord,
    LocalArtifactTypeRepository,
)
from ai_platform.workspace.storage.structured.code_package_repository import (
    LocalCodePackageRepository,
)
from ai_platform.workspace.storage.structured.job_definition_repository import (
    JobDefinitionRecord,
    LocalJobDefinitionRepository,
)
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig


# ---------------------------------------------------------------------------
# Catalog-reads fixtures: wire the three real routers behind a TestClient.
# ---------------------------------------------------------------------------


@pytest.fixture
def catalog_app(tmp_path: Path):
    file_repo = LocalFileRepository(
        LocalFileRepositoryConfig(root_dir=str(tmp_path), prefix="files")
    )
    jd_svc = JobDefinitionService(
        LocalJobDefinitionRepository(
            LocalRepositoryConfig(root_dir=str(tmp_path), prefix="job_definitions")
        )
    )
    at_svc = ArtifactTypeService(
        LocalArtifactTypeRepository(
            LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifact_types")
        )
    )
    cp_svc = CodePackageService(
        LocalCodePackageRepository(
            LocalRepositoryConfig(root_dir=str(tmp_path), prefix="code_packages")
        ),
        file_repo,
    )
    deps_mod._job_definition_service = jd_svc
    deps_mod._artifact_type_service = at_svc
    deps_mod._code_package_service = cp_svc

    app = FastAPI()
    app.include_router(job_defs_router.router)
    app.include_router(artifact_types_router.router)
    app.include_router(code_pkgs_router.router)
    app.dependency_overrides[deps_mod.get_job_definition_service] = lambda: jd_svc
    app.dependency_overrides[deps_mod.get_artifact_type_service] = lambda: at_svc
    app.dependency_overrides[deps_mod.get_code_package_service] = lambda: cp_svc
    return app, jd_svc, at_svc, cp_svc


@pytest.fixture
def catalog_session(catalog_app):
    app, *_ = catalog_app
    client = TestClient(app, base_url="http://fake")
    return PlatformSession.connect("http://fake", http_client=client)


def _jd_record(name: str = "math_qa", version: str = "1.0.0", **overrides) -> JobDefinitionRecord:
    base = dict(
        id=JobDefinitionRecord.make_id(name, version),
        name=name,
        version=version,
        runtime_selector="default",
        code_entrypoint="mathai.math_qa.execution:register_execution",
    )
    base.update(overrides)
    return JobDefinitionRecord(**base)


def _at_record(name: str = "math_question", version: str = "1.0.0", **overrides) -> ArtifactTypeRecord:
    base = dict(
        id=ArtifactTypeRecord.make_id(name, version),
        name=name,
        version=version,
        domain="math_qa",
        class_name="MathQuestionArtifact",
    )
    base.update(overrides)
    return ArtifactTypeRecord(**base)


# ---------------------------------------------------------------------------
# Catalog reads
# ---------------------------------------------------------------------------


def test_list_job_definitions_returns_typed_records(
    catalog_app, catalog_session
):
    _, jd_svc, _, _ = catalog_app
    jd_svc.deploy(_jd_record(name="a"))
    jd_svc.deploy(_jd_record(name="b", runtime_selector="crewai"))

    rows = catalog_session.list_job_definitions()
    assert {r.name for r in rows} == {"a", "b"}
    assert all(isinstance(r, JobDefinitionRecord) for r in rows)


def test_list_job_definitions_filters_by_runtime(catalog_app, catalog_session):
    _, jd_svc, _, _ = catalog_app
    jd_svc.deploy(_jd_record(name="a"))
    jd_svc.deploy(_jd_record(name="b", runtime_selector="crewai"))

    crewai = catalog_session.list_job_definitions(runtime_selector="crewai")
    assert [r.name for r in crewai] == ["b"]


def test_get_job_definition_returns_latest(catalog_app, catalog_session):
    _, jd_svc, _, _ = catalog_app
    jd_svc.deploy(_jd_record(name="math_qa", version="1.0.0"))
    jd_svc.deploy(_jd_record(name="math_qa", version="2.0.0"))

    got = catalog_session.get_job_definition("math_qa")
    assert got.version == "2.0.0"


def test_get_job_definition_missing_raises_jobnotfound(catalog_session):
    with pytest.raises(JobNotFound):
        catalog_session.get_job_definition("ghost")


def test_list_artifact_types_filters_by_domain(catalog_app, catalog_session):
    _, _, at_svc, _ = catalog_app
    at_svc.deploy(_at_record(name="a", domain="d1"))
    at_svc.deploy(_at_record(name="b", domain="d2"))

    d1 = catalog_session.list_artifact_types(domain="d1")
    assert [r.name for r in d1] == ["a"]


def test_list_code_packages(catalog_app, catalog_session):
    _, _, _, cp_svc = catalog_app
    cp_svc.deploy(
        name="toy",
        version="1.0.0",
        runtime_selector="default",
        filename="toy-1.0.0.whl",
        wheel_bytes=b"PKbytes",
    )
    rows = catalog_session.list_code_packages()
    assert len(rows) == 1
    assert rows[0].id == "toy@1.0.0"


# ---------------------------------------------------------------------------
# submit_job + JobHandle — fake API surface for lifecycle tests
# ---------------------------------------------------------------------------


class _FakeJobsAPI:
    """Tiny FastAPI app that mimics the jobs surface without the real
    GraphJobExecutor — drives the session through a deterministic
    state machine (PENDING -> RUNNING -> SUCCEEDED) per job_id.
    """

    def __init__(self):
        from fastapi import FastAPI, HTTPException

        self.app = FastAPI()
        self._jobs: dict[str, dict] = {}
        self._results: dict[str, dict] = {}
        self.submit_count = 0
        self._poll_counts: dict[str, int] = {}

        @self.app.post("/jobs/runs/submit")
        def submit(body: dict):
            self.submit_count += 1
            job_id = f"job-{self.submit_count}"
            self._jobs[job_id] = {
                "job_id": job_id,
                "job_type": body["job_type"],
                "status": "PENDING",
            }
            self._results[job_id] = {"job_id": job_id, "result": {"echo": body}}
            return {"job_id": job_id, "status": "PENDING"}

        @self.app.get("/jobs/{job_id}")
        def status(job_id: str):
            if job_id not in self._jobs:
                raise HTTPException(404, "not found")
            # Advance state machine each poll: PENDING -> RUNNING -> SUCCEEDED
            count = self._poll_counts.get(job_id, 0) + 1
            self._poll_counts[job_id] = count
            row = self._jobs[job_id]
            if count == 1:
                row["status"] = "RUNNING"
            elif count >= 2:
                row["status"] = "SUCCEEDED"
            return row

        @self.app.get("/jobs/{job_id}/result")
        def result(job_id: str):
            if job_id not in self._results:
                raise HTTPException(404, "not found")
            return self._results[job_id]


@pytest.fixture
def fake_jobs_session():
    fake = _FakeJobsAPI()
    client = TestClient(fake.app, base_url="http://fake")
    sess = PlatformSession.connect("http://fake", http_client=client)
    return sess, fake


def test_submit_job_with_dict_payload(fake_jobs_session):
    sess, fake = fake_jobs_session
    handle = sess.submit_job("math_qa", {"question": "what is 2+2?"})
    assert isinstance(handle, JobHandle)
    assert handle.job_id == "job-1"
    assert handle.job_type == "math_qa"
    assert fake.submit_count == 1


def test_submit_job_with_base_job_input(fake_jobs_session):
    """A BaseJobInput subclass should be `.model_dump()`-ed; the
    job_type discriminator is injected if missing.
    """
    sess, fake = fake_jobs_session

    class _Inp(BaseJobInput):
        job_type: Literal["math_qa"] = "math_qa"
        question: str = ""

    handle = sess.submit_job("math_qa", _Inp(question="2+2"))
    assert handle.job_id == "job-1"
    assert fake.submit_count == 1


def test_get_job_returns_handle_with_cached_type(fake_jobs_session):
    sess, _ = fake_jobs_session
    sess.submit_job("math_qa", {"question": "x"})
    h = sess.get_job("job-1")
    assert h.job_type == "math_qa"


def test_get_job_missing_raises_jobnotfound(fake_jobs_session):
    sess, _ = fake_jobs_session
    with pytest.raises(JobNotFound):
        sess.get_job("ghost")


def test_handle_status_calls_refresh_on_first_access(fake_jobs_session):
    sess, _ = fake_jobs_session
    h = sess.submit_job("math_qa", {})
    # State machine yields RUNNING on the first poll.
    assert h.status == "RUNNING"


def test_handle_is_done_for_terminal_statuses():
    sess = PlatformSession("http://fake", httpx.Client())
    h = JobHandle(session=sess, job_id="x", job_type="t")
    for st in ("SUCCEEDED", "FAILED", "CANCELLED", "WAITING_INPUT"):
        h._status_cache = {"status": st}
        assert h.is_done is True
    h._status_cache = {"status": "RUNNING"}
    assert h.is_done is False


# ---------------------------------------------------------------------------
# wait / result / timeout — sleep + monotonic patched for determinism
# ---------------------------------------------------------------------------


def test_wait_blocks_until_terminal_then_returns(fake_jobs_session):
    sess, _ = fake_jobs_session
    h = sess.submit_job("math_qa", {})

    with patch("ai_platform.session.session.time.sleep"):
        out = h.wait(timeout=10.0, poll_interval=0.01)

    assert out is h
    assert h.status == "SUCCEEDED"


def test_wait_raises_jobtimeout_when_deadline_passes(fake_jobs_session):
    sess, _ = fake_jobs_session
    h = sess.submit_job("math_qa", {})

    # Fake clock: every read is past the deadline so the first iteration
    # that isn't already terminal raises.
    clock = iter([0.0, 999.0, 999.0, 999.0])

    # Re-wire the FakeAPI so polls never advance to a terminal status —
    # otherwise wait() returns before checking the deadline.
    h._status_cache = {"status": "PENDING"}

    def _frozen_refresh():
        h._status_cache = {"status": "PENDING"}
        return h

    with patch.object(h, "refresh", side_effect=_frozen_refresh), patch(
        "ai_platform.session.session.time.monotonic", side_effect=lambda: next(clock)
    ), patch("ai_platform.session.session.time.sleep"):
        with pytest.raises(JobTimeout):
            h.wait(timeout=1.0, poll_interval=0.01)


def test_result_returns_payload_on_success(fake_jobs_session):
    sess, _ = fake_jobs_session
    h = sess.submit_job("math_qa", {"question": "x"})

    with patch("ai_platform.session.session.time.sleep"):
        result = h.result(timeout=10.0, poll_interval=0.01)

    # Our fake echoes the submission body.
    assert result["job_id"] == "job-1"
    assert result["result"] == {"echo": {"job_type": "math_qa", "question": "x"}}


def test_result_raises_for_failed_job(fake_jobs_session):
    """If the job is terminal-but-failed, `.result()` shouldn't try to
    fetch the result endpoint; it should surface the failure status.
    """
    sess, _ = fake_jobs_session
    h = sess.submit_job("math_qa", {})
    h._status_cache = {"status": "FAILED", "error_message": "boom"}

    with patch.object(h, "wait", return_value=h):
        with pytest.raises(PlatformSessionError, match="FAILED"):
            h.result()


def test_session_as_context_manager_closes_client():
    closed = {"flag": False}

    class _Stub:
        def close(self):
            closed["flag"] = True

    sess = PlatformSession("http://fake", _Stub())  # type: ignore[arg-type]
    with sess:
        pass
    assert closed["flag"] is True


# ---------------------------------------------------------------------------
# Media primitives — upload_media / download_media over the public client.
# ---------------------------------------------------------------------------


@pytest.fixture
def media_session(tmp_path: Path):
    from ai_platform.api.routers import media as media_router
    from ai_platform.jobs.media_service import MediaService

    file_repo = LocalFileRepository(
        LocalFileRepositoryConfig(root_dir=str(tmp_path), prefix="files")
    )
    service = MediaService(file_repo)
    deps_mod._media_service = service

    app = FastAPI()
    app.include_router(media_router.router)
    app.dependency_overrides[deps_mod.get_media_service] = lambda: service

    client = TestClient(app, base_url="http://fake")
    return PlatformSession.connect("http://fake", http_client=client)


def test_upload_then_download_media_round_trips(media_session: PlatformSession):
    ref = media_session.upload_media(
        filename="voice.m4a", data=b"fake-audio-bytes", content_type="audio/m4a"
    )
    assert ref.storage_ref.startswith("media/")
    assert ref.filename == "voice.m4a"
    assert ref.content_type == "audio/m4a"
    assert ref.byte_size == len(b"fake-audio-bytes")

    # download_media returns raw bytes (not JSON-unwrapped).
    assert media_session.download_media(ref.storage_ref) == b"fake-audio-bytes"


def test_download_media_missing_raises(media_session: PlatformSession):
    from ai_platform.session.session import MediaNotFound

    with pytest.raises(MediaNotFound):
        media_session.download_media("media/does-not-exist/x.m4a")
