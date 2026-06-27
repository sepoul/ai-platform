"""ApiClient + deploy-catalog tests for aiplatform-cli.

Uses `httpx.MockTransport` so the full request/response path runs without
a live server — asserting the CLI hits the right endpoints with the right
payloads, in the right order.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from aiplatform_cli.api import ApiClient, ApiConnectionError, ApiError
from aiplatform_cli.deploy import deploy_catalog, load_catalog, resolve_wheel_path


def _record_transport(captured: list[httpx.Request], *, status: int = 200,
                      json_body: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = json_body if json_body is not None else {"id": "srv-id", "name": "srv-name"}
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# ApiClient
# ---------------------------------------------------------------------------

def test_client_sends_token_header_and_hits_path():
    captured: list[httpx.Request] = []
    client = ApiClient("https://p:8000", token="abc", transport=_record_transport(captured))
    with client:
        client.create_job_definition({"name": "demo"})

    req = captured[-1]
    assert req.method == "POST"
    assert str(req.url) == "https://p:8000/job-definitions"
    assert req.headers["Authorization"] == "Bearer abc"
    assert json.loads(req.content) == {"name": "demo"}


def test_client_raises_apierror_on_non_2xx():
    transport = _record_transport([], status=409, json_body={"detail": "already terminal"})
    with ApiClient("https://p", transport=transport) as client:
        with pytest.raises(ApiError) as exc:
            client.cancel_job("job-1")
    assert exc.value.status == 409
    assert "already terminal" in exc.value.body


def test_client_wraps_transport_error_as_apiconnectionerror():
    """A refused/unreachable host must surface as a clean ApiError
    subclass, not a raw httpx traceback."""
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    with ApiClient("https://p", transport=httpx.MockTransport(boom)) as client:
        with pytest.raises(ApiConnectionError) as exc:
            client.list_jobs()
    # It IS an ApiError, so handlers catching ApiError surface it cleanly.
    assert isinstance(exc.value, ApiError)
    assert "connection failed" in str(exc.value)


def test_list_jobs_passes_filters_as_query():
    captured: list[httpx.Request] = []
    with ApiClient("https://p", transport=_record_transport(captured, json_body=[])) as client:
        client.list_jobs(status="RUNNING", job_type="demo")
    req = captured[-1]
    assert req.url.params["status"] == "RUNNING"
    assert req.url.params["job_type"] == "demo"


def test_cancel_job_posts_to_cancel_path():
    captured: list[httpx.Request] = []
    with ApiClient("https://p", transport=_record_transport(captured, json_body={"status": "CANCELLED"})) as client:
        out = client.cancel_job("job-9")
    assert captured[-1].method == "POST"
    assert str(captured[-1].url) == "https://p/jobs/job-9/cancel"
    assert out["status"] == "CANCELLED"


def test_push_workflows_posts_wrapped_map():
    captured: list[httpx.Request] = []
    body = {"job_types": ["demo", "other"]}
    with ApiClient("https://p", transport=_record_transport(captured, json_body=body)) as client:
        out = client.push_workflows({"demo": {"job_type": "demo", "stages": [], "edges": []}})
    req = captured[-1]
    assert req.method == "POST"
    assert str(req.url) == "https://p/workflows"
    # The map is wrapped under the "workflows" key the endpoint expects.
    assert json.loads(req.content) == {
        "workflows": {"demo": {"job_type": "demo", "stages": [], "edges": []}}
    }
    assert out["job_types"] == ["demo", "other"]


# ---------------------------------------------------------------------------
# deploy_catalog
# ---------------------------------------------------------------------------

def _sample_catalog() -> dict:
    return {
        "aiplatform_manifest_version": 1,
        "code_package": {
            "name": "aiplatform-demo",
            "version": "0.1.0",
            "runtime_selector": "default",
            "wheel": "dist/demo.whl",
        },
        "job_definitions": [{"name": "demo", "version": "0.1.0"}],
        "artifact_types": [{"name": "demo_echo", "version": "0.1.0"}],
        "prompts": [{"name": "demo.greet", "domain": "demo"}],
    }


def test_deploy_catalog_posts_in_order(tmp_path: Path):
    wheel = tmp_path / "demo.whl"
    wheel.write_bytes(b"PK\x03\x04 fake wheel")

    captured: list[httpx.Request] = []
    transport = _record_transport(captured)
    with ApiClient("https://p", transport=transport) as client:
        report = deploy_catalog(client, _sample_catalog(), wheel_path=wheel)

    paths = [r.url.path for r in captured]
    # CodePackage bytes must land before the JobDefinition that references them.
    assert paths == [
        "/code-packages",
        "/job-definitions",
        "/artifact-types",
        "/prompts",
    ]
    # Wheel went up as multipart, not JSON.
    assert captured[0].headers["content-type"].startswith("multipart/form-data")
    assert report["job_definitions"] == ["srv-id"]
    # Prompts record name + the server's upsert action (issue #59); the
    # default mock body has no action, so it falls back to "deployed".
    assert report["prompts"] == [{"name": "srv-name", "action": "deployed"}]


def test_deploy_catalog_surfaces_prompt_action(tmp_path: Path):
    """The server's created/updated/unchanged action is carried into the
    deploy report so a silently-dropped edit can't hide (issue #59)."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompts":
            return httpx.Response(200, json={"name": "demo.greet", "action": "updated"})
        return httpx.Response(200, json={"id": "x"})

    with ApiClient("https://p", transport=httpx.MockTransport(handler)) as client:
        report = deploy_catalog(client, _sample_catalog(), skip_wheel=True)
    assert report["prompts"] == [{"name": "demo.greet", "action": "updated"}]


def test_deploy_catalog_skip_wheel_omits_code_package(tmp_path: Path):
    captured: list[httpx.Request] = []
    with ApiClient("https://p", transport=_record_transport(captured)) as client:
        report = deploy_catalog(client, _sample_catalog(), skip_wheel=True)
    paths = [r.url.path for r in captured]
    assert "/code-packages" not in paths
    assert report["code_package"] is None


def test_deploy_catalog_requires_wheel_unless_skipped():
    with ApiClient("https://p", transport=_record_transport([])) as client:
        with pytest.raises(ValueError, match="wheel_path is required"):
            deploy_catalog(client, _sample_catalog())


# ---------------------------------------------------------------------------
# load_catalog / resolve_wheel_path
# ---------------------------------------------------------------------------

def test_load_catalog_rejects_unknown_version(tmp_path: Path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"aiplatform_manifest_version": 99}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported catalog version"):
        load_catalog(path)


def test_load_catalog_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_catalog(tmp_path / "nope.json")


def test_resolve_wheel_path_is_relative_to_catalog(tmp_path: Path):
    catalog_file = tmp_path / "build" / "catalog.json"
    catalog_file.parent.mkdir()
    catalog_file.write_text("{}", encoding="utf-8")
    wheel = resolve_wheel_path(_sample_catalog(), catalog_file)
    assert wheel == (tmp_path / "build" / "dist" / "demo.whl").resolve()
