"""Worker boot-time code-package install.

Reads the CodePackage catalog for the worker's `runtime_selector`,
downloads any wheels the worker doesn't already have at the matching
version, and `pip install`s them into the running interpreter.

Posture:
- **Best-effort.** A single failed install logs + continues. The worker
  can still serve the JobDefinitions whose code is already baked into
  the image (math_qa, math_conversation). A friend's package failing to
  install means *their* jobs are unserved, not that the worker is dead.
- **Idempotent.** Already-installed packages at the catalog version
  are skipped — re-boot is a no-op. `(name, version)` is the comparison
  key; if either differs we re-install.
- **Trust-the-bundle.** `pip install` runs with default dep resolution,
  i.e. the friend's wheel can pull in its own runtime deps. This is
  YOLO-mode for v1 — friends deploying to *their* platform get to
  decide their dep set. A hardened mode (constraints, sandboxed pip,
  signature check) lands later if needed.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from importlib import metadata as _metadata
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_platform.jobs.code_package_service import CodePackageService
    from ai_platform.workspace.storage.structured.code_package_repository import (
        CodePackageRecord,
    )


_logger = logging.getLogger(__name__)


def install_packages_for_runtime(
    runtime_selector: str,
    code_package_service: "CodePackageService",
) -> list[str]:
    """Install every CodePackage catalog row for this runtime.

    Returns the list of package ids that were installed (excludes
    already-present ones). Failures are logged + swallowed — the
    returned list reflects what actually landed.
    """
    try:
        records = code_package_service.list(runtime_selector=runtime_selector)
    except Exception as exc:  # noqa: BLE001 — best-effort
        _logger.warning(
            "Failed to list CodePackages for runtime=%s: %s — skipping install",
            runtime_selector, exc,
        )
        return []

    if not records:
        _logger.info("No CodePackages registered for runtime=%s", runtime_selector)
        return []

    installed: list[str] = []
    for record in records:
        if _is_already_installed(record):
            _logger.info(
                "CodePackage %s already installed at version %s — skipping",
                record.name, record.version,
            )
            continue
        try:
            _download_and_install(record, code_package_service)
            installed.append(record.id)
            _logger.info("Installed CodePackage %s", record.id)
        except Exception as exc:  # noqa: BLE001 — best-effort
            _logger.warning("Failed to install CodePackage %s: %s", record.id, exc)
    return installed


def _is_already_installed(record: "CodePackageRecord") -> bool:
    """True iff the distribution `record.name` is importable and
    `importlib.metadata.version(record.name)` equals `record.version`.
    """
    try:
        installed_version = _metadata.version(record.name)
    except _metadata.PackageNotFoundError:
        return False
    return installed_version == record.version


def _download_and_install(
    record: "CodePackageRecord", service: "CodePackageService"
) -> None:
    """Fetch the blob (sha256-verified by the service) to a temp file
    and `pip install` it into the current interpreter.
    """
    _, wheel_bytes = service.download(record.id)
    with tempfile.NamedTemporaryFile(
        prefix=f"{record.name}-", suffix=".whl", delete=False
    ) as fh:
        fh.write(wheel_bytes)
        wheel_path = Path(fh.name)

    try:
        # `--force-reinstall` covers the case where a *different* version
        # is currently installed (e.g. catalog bumped from 1.0.0 to 1.0.1).
        # `_is_already_installed` already short-circuits the exact-match
        # case, so we won't re-install identical bytes.
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--force-reinstall", str(wheel_path)],
            check=True,
            capture_output=True,
        )
    finally:
        wheel_path.unlink(missing_ok=True)
