"""Thin HTTP client over the platform's OpenAPI surface.

Every method is one request to one documented endpoint. No platform
internals are imported — payloads are plain dicts (produced upstream by
`aiplatform export-manifest`) and responses are returned as parsed JSON.

A custom `httpx` transport can be injected (`transport=`) so tests run
the full request/response path without a live server.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

DEFAULT_TIMEOUT = 30.0


class ApiError(RuntimeError):
    """A non-2xx response from the platform, with status + body for context."""

    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"{method} {url} → HTTP {status}: {body[:500]}")


class ApiConnectionError(ApiError):
    """A transport-level failure (host unreachable, timeout, DNS) — no
    HTTP response. Subclasses `ApiError` so command handlers that catch
    `ApiError` surface it as a clean message instead of a traceback."""

    def __init__(self, method: str, url: str, message: str) -> None:
        self.status = None  # type: ignore[assignment]
        self.body = message
        RuntimeError.__init__(self, f"{method} {url} → connection failed: {message}")


class ApiClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"User-Agent": "aiplatform-cli"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers=headers,
            transport=transport,
        )

    # -- lifecycle ----------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- request plumbing ---------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            # Transport failure (no response): unreachable host, timeout,
            # DNS, refused connection. Surface cleanly, not as a traceback.
            url = str(exc.request.url) if exc.request else f"{self.base_url}{path}"
            raise ApiConnectionError(method, url, str(exc)) from exc
        if resp.status_code >= 400:
            raise ApiError(method, str(resp.request.url), resp.status_code, resp.text)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # -- write path (deploy) ------------------------------------------------
    def upload_code_package(
        self, wheel_path: str | Path, *, name: str, version: str, runtime_selector: str
    ) -> dict[str, Any]:
        path = Path(wheel_path)
        if not path.exists():
            raise FileNotFoundError(f"Wheel not found: {path}")
        with path.open("rb") as fh:
            files = {"wheel": (path.name, fh, "application/octet-stream")}
            data = {"name": name, "version": version, "runtime_selector": runtime_selector}
            return self._request("POST", "/code-packages", files=files, data=data)

    def create_job_definition(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/job-definitions", json=record)

    def create_artifact_type(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/artifact-types", json=record)

    def create_prompt(self, prompt: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/prompts", json=prompt)

    # -- read path ----------------------------------------------------------
    def get_openapi(self) -> dict[str, Any]:
        return self._request("GET", "/openapi.json")

    def list_job_definitions(self) -> Any:
        return self._request("GET", "/job-definitions")

    def list_artifact_types(self) -> Any:
        return self._request("GET", "/artifact-types")

    def list_jobs(self, *, status: str | None = None, job_type: str | None = None) -> Any:
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        if job_type:
            params["job_type"] = job_type
        return self._request("GET", "/jobs", params=params or None)

    def list_workflows(self) -> Any:
        return self._request("GET", "/workflows")

    def push_workflows(self, workflows: dict[str, Any]) -> dict[str, Any]:
        """Merge-upsert workflow descriptors (`{job_type: descriptor}`) into
        the platform's workflows blob (POST /workflows, issue #56)."""
        return self._request("POST", "/workflows", json={"workflows": workflows})

    # -- recovery (relies on POST /jobs/{id}/cancel, issue #48) -------------
    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._request("POST", f"/jobs/{job_id}/cancel")
