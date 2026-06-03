"""PlatformSession + JobHandle implementations.

Both are thin HTTP wrappers over the platform API. `PlatformSession`
owns the `httpx.Client` (so connection pooling + auth headers live in
one place); `JobHandle` holds a back-reference to the session and an
opaque `job_id`.

Tests inject an `httpx.Client` directly (a TestClient or a mock) via
the `http_client` kwarg on `connect()`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

import httpx

from ai_platform.jobs.input import BaseJobInput
from ai_platform.workspace.storage.structured.artifact_type_repository import (
    ArtifactTypeRecord,
)
from ai_platform.workspace.storage.structured.code_package_repository import (
    CodePackageRecord,
)
from ai_platform.workspace.storage.structured.job_definition_repository import (
    JobDefinitionRecord,
)

if TYPE_CHECKING:
    pass


_TERMINAL_STATUSES = frozenset(
    {"SUCCEEDED", "FAILED", "CANCELLED", "WAITING_INPUT"}
)


class PlatformSessionError(RuntimeError):
    """Raised when the API responds with a non-2xx that the session
    can't translate into a domain error (e.g. ObjectNotFound)."""


class JobNotFound(PlatformSessionError):
    pass


class JobTimeout(PlatformSessionError):
    pass


class PlatformSession:
    """Spark-session-style entry point to a running ai-platform.

    One per process, typically. Owns the httpx client + URL config.
    Construct via the `connect` classmethod; tests pass `http_client=`
    to bypass real network.
    """

    def __init__(self, api_url: str, client: httpx.Client) -> None:
        self._api_url = api_url.rstrip("/")
        self._client = client

    @classmethod
    def connect(
        cls,
        api_url: str,
        *,
        timeout: float = 30.0,
        http_client: Optional[httpx.Client] = None,
    ) -> "PlatformSession":
        """Open a session against the platform at `api_url`.

        `http_client` is the override seam tests use to point at a
        FastAPI TestClient; production callers leave it unset and the
        session manages its own httpx.Client lifetime.
        """
        client = http_client or httpx.Client(base_url=api_url, timeout=timeout)
        return cls(api_url, client)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PlatformSession":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # ---- catalog reads ----

    def list_job_definitions(
        self, *, runtime_selector: Optional[str] = None
    ) -> list[JobDefinitionRecord]:
        params = {"runtime_selector": runtime_selector} if runtime_selector else None
        resp = self._get("/job-definitions", params=params)
        return [JobDefinitionRecord.model_validate(r) for r in resp]

    def get_job_definition(self, name: str) -> JobDefinitionRecord:
        return JobDefinitionRecord.model_validate(
            self._get(f"/job-definitions/by-name/{name}", expect=200)
        )

    def list_artifact_types(
        self, *, domain: Optional[str] = None
    ) -> list[ArtifactTypeRecord]:
        params = {"domain": domain} if domain else None
        resp = self._get("/artifact-types", params=params)
        return [ArtifactTypeRecord.model_validate(r) for r in resp]

    def list_code_packages(
        self, *, runtime_selector: Optional[str] = None
    ) -> list[CodePackageRecord]:
        params = {"runtime_selector": runtime_selector} if runtime_selector else None
        resp = self._get("/code-packages", params=params)
        return [CodePackageRecord.model_validate(r) for r in resp]

    # ---- job lifecycle ----

    def submit_job(
        self, job_type: str, payload: dict | BaseJobInput
    ) -> "JobHandle":
        """Submit a job by `job_type` (the JobControl name). `payload`
        is either a dict of submission params or a `BaseJobInput`
        subclass instance (which `.model_dump()`s the same way).

        Returns a `JobHandle` whose `.wait()` / `.result()` drive the
        rest of the lifecycle.
        """
        if isinstance(payload, BaseJobInput):
            body = payload.model_dump()
        else:
            body = dict(payload)
        body.setdefault("job_type", job_type)

        resp = self._post("/jobs/runs/submit", json=body, expect=200)
        return JobHandle(session=self, job_id=resp["job_id"], job_type=job_type)

    def get_job(self, job_id: str) -> "JobHandle":
        """Return a handle for an existing job. `.refresh()` populates
        the cached status; we don't poll here so a friend can hold a
        handle without triggering a network call.
        """
        # Probe the API so a wrong id fails fast.
        raw = self._get(f"/jobs/{job_id}", expect=200)
        return JobHandle(session=self, job_id=job_id, job_type=raw["job_type"])

    # ---- internal HTTP plumbing ----

    def _get(
        self,
        path: str,
        *,
        params: Optional[dict] = None,
        expect: int = 200,
    ) -> Any:
        resp = self._client.get(path, params=params)
        return self._unwrap(resp, expect)

    def _post(
        self, path: str, *, json: Any, expect: int = 201
    ) -> Any:
        resp = self._client.post(path, json=json)
        return self._unwrap(resp, expect)

    @staticmethod
    def _unwrap(resp: httpx.Response, expect: int) -> Any:
        if resp.status_code == 404:
            raise JobNotFound(resp.text)
        if resp.status_code != expect and not (200 <= resp.status_code < 300):
            raise PlatformSessionError(
                f"{resp.request.method} {resp.request.url}: {resp.status_code} {resp.text}"
            )
        return resp.json()


@dataclass
class JobHandle:
    """Pointer to a running / completed job.

    The handle doesn't auto-poll; call `.refresh()` to pull the latest
    status, or `.wait()` to block until terminal. `.result()` is
    `.wait()` followed by a result fetch.
    """

    session: PlatformSession
    job_id: str
    job_type: str
    _status_cache: Optional[dict] = None

    def refresh(self) -> "JobHandle":
        """Pull latest status from the API. Returns self for chaining."""
        self._status_cache = self.session._get(f"/jobs/{self.job_id}", expect=200)
        return self

    @property
    def status(self) -> str:
        """Last-fetched status string. Calls `.refresh()` if the cache
        is empty (i.e. user called `.status` before `.refresh()` on a
        freshly-constructed handle).
        """
        if self._status_cache is None:
            self.refresh()
        return self._status_cache["status"]  # type: ignore[index]

    @property
    def is_done(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    def wait(
        self,
        *,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
    ) -> "JobHandle":
        """Block (poll) until the job reaches a terminal status or
        `timeout` elapses (then raise `JobTimeout`).
        """
        deadline = time.monotonic() + timeout
        while True:
            self.refresh()
            if self.is_done:
                return self
            if time.monotonic() >= deadline:
                raise JobTimeout(
                    f"Job {self.job_id} did not reach terminal state in {timeout}s "
                    f"(last status: {self.status})"
                )
            time.sleep(poll_interval)

    def result(
        self, *, timeout: float = 60.0, poll_interval: float = 1.0
    ) -> dict:
        """Wait for completion + return the result payload.

        Raises `JobTimeout` if the job doesn't finish in `timeout` and
        `PlatformSessionError` if the job reached a terminal status
        without a fetchable result (e.g. FAILED — the caller should
        inspect `.status_payload` for `error_message`).
        """
        self.wait(timeout=timeout, poll_interval=poll_interval)
        if self.status != "SUCCEEDED" and self.status != "WAITING_INPUT":
            err = (self._status_cache or {}).get("error_message")
            raise PlatformSessionError(
                f"Job {self.job_id} ended in {self.status}: {err}"
            )
        return self.session._get(f"/jobs/{self.job_id}/result", expect=200)

    @property
    def status_payload(self) -> dict:
        """The full last-fetched status row (status + stage + percent +
        message + error_message + result preview).
        """
        if self._status_cache is None:
            self.refresh()
        return dict(self._status_cache or {})
