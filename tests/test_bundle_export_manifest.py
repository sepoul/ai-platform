"""Tests for the domain-side build step (issue #49): `build_manifest`
and the `aiplatform export-manifest` CLI command.

These run *in-process* (they import a domain to introspect it) — that's
exactly the responsibility split: the build is domain-side, the transport
(`aiplatform-cli`) is pure HTTP. We use the bundled `_demo` domain as the
domain under test, so no external package is needed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_platform.bundle import build_manifest
from ai_platform.bundle.cli import main as bundle_main

_DEMO_BUNDLE = """
[package]
name    = "aiplatform-demo"
version = "0.1.0"
runtime = "default"
wheel   = "dist/aiplatform_demo-0.1.0-py3-none-any.whl"

[control]
domain               = "demo"
control_entrypoint   = "aiplatform_demo.control:register_control"
execution_entrypoint = "aiplatform_demo.execution:register_execution"
"""


@pytest.fixture
def demo_bundle(tmp_path: Path) -> Path:
    path = tmp_path / "bundle.toml"
    path.write_text(_DEMO_BUNDLE, encoding="utf-8")
    return path


def test_build_manifest_shape(demo_bundle: Path):
    catalog = build_manifest(demo_bundle)

    assert catalog["aiplatform_manifest_version"] == 1
    assert catalog["code_package"] == {
        "name": "aiplatform-demo",
        "version": "0.1.0",
        "runtime_selector": "default",
        "wheel": "dist/aiplatform_demo-0.1.0-py3-none-any.whl",
    }

    # The demo domain declares one JobControl ("demo") and at least one
    # artifact type — both introspected from the live control plane.
    job_defs = catalog["job_definitions"]
    assert [jd["name"] for jd in job_defs] == ["demo"]
    jd = job_defs[0]
    assert jd["runtime_selector"] == "default"
    assert jd["code_entrypoint"] == "aiplatform_demo.execution:register_execution"
    assert jd["control_entrypoint"] == "aiplatform_demo.control:register_control"
    # Schemas are real JSON Schemas, ready to POST verbatim.
    assert jd["input_schema"]["type"] == "object"
    assert jd["result_schema"]["type"] == "object"

    assert len(catalog["artifact_types"]) >= 1
    for at in catalog["artifact_types"]:
        assert at["domain"] == "demo"
        assert at["json_schema"]["type"] == "object"


def test_build_manifest_records_match_deploy_record_builders(demo_bundle: Path):
    """The catalog records must be byte-for-byte what `deploy_bundle`
    would POST — i.e. produced by the same `build_record` /
    `build_artifact_type_record` helpers — so the split is faithful.
    """
    from ai_platform.bundle import (
        _resolve_entrypoint,
        _stub_bootstrap_ctx,
        build_artifact_type_record,
        build_record,
    )

    # `deployed_at` / `updated_at` default to wall-clock now() per build, so
    # strip them before comparing the *semantic* payload.
    _VOLATILE = ("deployed_at", "updated_at")

    def _stable(record: dict) -> dict:
        return {k: v for k, v in record.items() if k not in _VOLATILE}

    catalog = build_manifest(demo_bundle)
    register = _resolve_entrypoint("aiplatform_demo.control:register_control")
    domain = register(_stub_bootstrap_ctx())

    expected_jd = build_record(
        domain.job_controls[0],
        runtime="default",
        code_entrypoint="aiplatform_demo.execution:register_execution",
        control_entrypoint="aiplatform_demo.control:register_control",
        version="0.1.0",
        artifact_types=tuple(domain.artifact_types),
    ).model_dump(mode="json")
    assert _stable(catalog["job_definitions"][0]) == _stable(expected_jd)

    expected_ats = [
        build_artifact_type_record(cls, domain="demo", version="0.1.0").model_dump(mode="json")
        for cls in domain.artifact_types
        if build_artifact_type_record(cls, domain="demo", version="0.1.0") is not None
    ]
    assert [_stable(a) for a in catalog["artifact_types"]] == [_stable(a) for a in expected_ats]


def test_export_manifest_cli_writes_json(demo_bundle: Path, tmp_path: Path, capsys):
    out = tmp_path / "catalog.json"
    rc = bundle_main(["export-manifest", "--bundle", str(demo_bundle), "-o", str(out)])
    assert rc == 0, capsys.readouterr()
    assert out.exists()

    catalog = json.loads(out.read_text(encoding="utf-8"))
    assert catalog["aiplatform_manifest_version"] == 1
    assert catalog["job_definitions"][0]["name"] == "demo"


def test_export_manifest_cli_missing_bundle_returns_2(tmp_path: Path):
    rc = bundle_main(["export-manifest", "--bundle", str(tmp_path / "nope.toml")])
    assert rc == 2
