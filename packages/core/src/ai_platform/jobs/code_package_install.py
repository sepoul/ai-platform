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

    Worker-side entrypoint. Pulls wheels for one `runtime_selector`
    and installs with the `[execution]` extra so the LLM stack
    (pydantic-ai-slim / crewai) lands alongside the base package.

    Returns the list of package ids that were installed (excludes
    already-present ones). Failures are logged + swallowed — the
    returned list reflects what actually landed.
    """
    return _install_all(
        code_package_service,
        runtime_selector=runtime_selector,
        extras=["execution"],
        scope=f"runtime={runtime_selector}",
    )


def install_control_packages_for_api(
    code_package_service: "CodePackageService",
) -> list[str]:
    """Install every CodePackage's *control modules* on API boot.

    API-side analog of `install_packages_for_runtime`. The API is
    runtime-agnostic — it imports control modules across every
    runtime so `register_control_domains` can introspect their
    JobControls + artifact types. It does NOT need the runtime LLM
    stack (`pydantic-ai-slim`, `crewai`), because control modules
    are engine-free by construction (enforced via
    `ai_platform.jobs.import_guard`).

    The two diffs from the worker path:
    1. No `runtime_selector` filter — install everything in the catalog.
    2. No `[execution]` extra on the install target.

    Best-effort, same as the worker version: failures log + continue.
    A degraded API still serves whatever domains the previous boot's
    install pass + the current image baseline produce.
    """
    return _install_all(
        code_package_service,
        runtime_selector=None,
        extras=[],
        scope="api control plane",
    )


def _install_all(
    code_package_service: "CodePackageService",
    *,
    runtime_selector: str | None,
    extras: list[str],
    scope: str,
) -> list[str]:
    try:
        if runtime_selector is None:
            records = code_package_service.list()
        else:
            records = code_package_service.list(runtime_selector=runtime_selector)
    except Exception as exc:  # noqa: BLE001 — best-effort
        _logger.warning(
            "Failed to list CodePackages for %s: %s — skipping install",
            scope, exc,
        )
        return []

    if not records:
        _logger.info("No CodePackages registered for %s", scope)
        return []

    # The catalog can hold several versions of the same package (each deploy
    # upserts a new (name, version) row). Installing *every* row makes the
    # final installed version order-dependent — a later-listed older row can
    # downgrade a newer one that was installed earlier in the same pass. Keep
    # only the latest version per name so a version bump reliably wins.
    records = _latest_per_name(records)

    installed: list[str] = []
    for record in records:
        if _is_already_installed(record):
            _logger.info(
                "CodePackage %s already installed at version %s — skipping",
                record.name, record.version,
            )
            continue
        try:
            _download_and_install(record, code_package_service, extras=extras)
            installed.append(record.id)
            _logger.info("Installed CodePackage %s", record.id)
        except Exception as exc:  # noqa: BLE001 — best-effort
            _logger.warning("Failed to install CodePackage %s: %s", record.id, exc)
    return installed


def _latest_per_name(records: list) -> list:
    """Collapse a CodePackage list to the highest-version row per name.

    Version order uses PEP 440 (`packaging.version`); an unparseable version
    sorts lowest so a malformed row never shadows a valid one.
    """
    from packaging.version import InvalidVersion, Version

    def _key(v: str) -> "Version":
        try:
            return Version(v)
        except InvalidVersion:
            return Version("0")

    best: dict[str, object] = {}
    for record in records:
        current = best.get(record.name)
        if current is None or _key(record.version) > _key(current.version):
            best[record.name] = record
    return list(best.values())


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
    record: "CodePackageRecord",
    service: "CodePackageService",
    *,
    extras: list[str],
) -> None:
    """Fetch the blob (sha256-verified by the service) to a temp file
    and `pip install` it into the current interpreter.

    Two non-obvious bits:

    1. The temp file MUST keep the original `record.filename` — pip parses
       the wheel name to derive `{name}-{version}`, and a randomized
       `tempfile.NamedTemporaryFile` suffix breaks that (PEP 427:
       "Invalid wheel filename (wrong number of parts)"). We use a temp
       *directory* and write the wheel inside under its real filename.

    2. `extras` (a list like `["execution"]`) is appended to the install
       target so pip resolves the wheel's optional dep set. The worker
       path passes `["execution"]` (platform convention: runtime-side
       LLM stack lives under that extra). The API path passes `[]` —
       control modules only, no LLM deps. pip warns + continues if the
       extra doesn't exist, so a friend's wheel that uses a different
       name still installs its base package — just without the runtime
       stack. The convention is documented in
       `packages/{math-qa,math-conversation}/bundle.toml`.

    No `--force-reinstall`: it would also try to reinstall transitive
    deps like `aiplatform-core`, which is path-source-only and not on
    PyPI. Plain `pip install` upgrades the target wheel and resolves
    new deps but leaves already-satisfied ones (including aiplatform-core)
    alone.
    """
    _, wheel_bytes = service.download(record.id)
    tmpdir = Path(tempfile.mkdtemp(prefix="codepkg-"))
    wheel_path = tmpdir / record.filename
    wheel_path.write_bytes(wheel_bytes)

    suffix = f"[{','.join(extras)}]" if extras else ""
    target = f"{wheel_path}{suffix}"

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", target],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            # Surface pip's stderr — the bare CalledProcessError swallows
            # the actual failure (e.g. "Invalid wheel filename"), which
            # turned a wheel-naming bug into an inscrutable boot warning.
            raise RuntimeError(
                f"pip install failed (rc={proc.returncode}): {proc.stderr.strip()[:500]}"
            )
    finally:
        wheel_path.unlink(missing_ok=True)
        tmpdir.rmdir()
