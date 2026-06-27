"""Catalog deploy — the pure-HTTP transport of a precomputed catalog.

Consumes the JSON emitted by `aiplatform export-manifest` (the domain-side
build, in `aiplatform-core`) and replays it against a deployment over HTTP.
No domain import, no introspection here — that already happened upstream.

Order mirrors the in-process `deploy_bundle`: the CodePackage bytes must
land before the JobDefinitions that reference the entrypoint inside the
wheel; ArtifactTypes and prompts follow. Every underlying POST is
idempotent on `(name, version)` server-side, so a re-run after a midway
failure picks up cleanly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aiplatform_cli.api import ApiClient

SUPPORTED_MANIFEST_VERSION = 1


def load_catalog(catalog_path: str | Path) -> dict[str, Any]:
    """Read + lightly validate a catalog JSON file."""
    path = Path(catalog_path)
    if not path.exists():
        raise FileNotFoundError(f"Catalog not found: {path}")
    catalog = json.loads(path.read_text(encoding="utf-8"))
    version = catalog.get("aiplatform_manifest_version")
    if version != SUPPORTED_MANIFEST_VERSION:
        raise ValueError(
            f"Unsupported catalog version {version!r} "
            f"(this CLI understands {SUPPORTED_MANIFEST_VERSION}). "
            "Regenerate with a matching `aiplatform export-manifest`."
        )
    return catalog


def resolve_wheel_path(catalog: dict[str, Any], catalog_path: str | Path) -> Path:
    """Resolve the wheel referenced by the catalog, relative to the catalog file."""
    wheel = (catalog.get("code_package") or {}).get("wheel")
    if not wheel:
        raise ValueError("Catalog has no code_package.wheel to upload")
    return (Path(catalog_path).resolve().parent / wheel).resolve()


def deploy_catalog(
    client: ApiClient,
    catalog: dict[str, Any],
    *,
    wheel_path: str | Path | None = None,
    skip_wheel: bool = False,
) -> dict[str, Any]:
    """POST a catalog to the platform. Returns a report dict of ids."""
    report: dict[str, Any] = {
        "code_package": None,
        "job_definitions": [],
        "artifact_types": [],
        "prompts": [],
    }

    code_pkg = catalog.get("code_package") or {}

    # 1. CodePackage — bytes first so a worker booted mid-deploy can install.
    if not skip_wheel:
        if wheel_path is None:
            raise ValueError("wheel_path is required unless skip_wheel=True")
        result = client.upload_code_package(
            wheel_path,
            name=code_pkg["name"],
            version=code_pkg["version"],
            runtime_selector=code_pkg["runtime_selector"],
        )
        report["code_package"] = (result or {}).get("id")

    # 2. JobDefinitions — reference the entrypoint inside the wheel.
    for record in catalog.get("job_definitions", []):
        result = client.create_job_definition(record)
        report["job_definitions"].append((result or {}).get("id"))

    # 3. ArtifactTypes.
    for record in catalog.get("artifact_types", []):
        result = client.create_artifact_type(record)
        report["artifact_types"].append((result or {}).get("id"))

    # 4. Prompts. The server upserts by content and reports the action
    #    (created / updated / unchanged) so a stale edit can't hide behind a
    #    blanket success (issue #59).
    for prompt in catalog.get("prompts", []):
        result = client.create_prompt(prompt) or {}
        report["prompts"].append(
            {
                "name": result.get("name", prompt.get("name")),
                "action": result.get("action", "deployed"),
            }
        )

    return report
