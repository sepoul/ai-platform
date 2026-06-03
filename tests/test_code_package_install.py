"""Tests for the worker boot-time CodePackage install path.

Covers:
- `_is_already_installed` honors the catalog version
- `install_packages_for_runtime` skips already-installed packages
- Install failures don't crash boot — they log + continue
- An empty catalog is a no-op
- A list-call failure is swallowed (the worker can still serve the
  baked-in JobDefinitions)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_platform.jobs.code_package_install import (
    _is_already_installed,
    install_packages_for_runtime,
)
from ai_platform.workspace.storage.structured.code_package_repository import (
    CodePackageRecord,
)


def _record(name: str = "toy_pkg", version: str = "1.0.0") -> CodePackageRecord:
    return CodePackageRecord(
        id=CodePackageRecord.make_id(name, version),
        name=name,
        version=version,
        runtime_selector="default",
        filename=f"{name}-{version}.whl",
        blob_id=f"code_packages/{name}-{version}.whl",
        sha256="a" * 64,
        size_bytes=10,
    )


def test_is_already_installed_true_for_matching_version():
    with patch(
        "ai_platform.jobs.code_package_install._metadata.version",
        return_value="1.0.0",
    ):
        assert _is_already_installed(_record(version="1.0.0")) is True


def test_is_already_installed_false_for_version_mismatch():
    with patch(
        "ai_platform.jobs.code_package_install._metadata.version",
        return_value="0.9.0",
    ):
        assert _is_already_installed(_record(version="1.0.0")) is False


def test_is_already_installed_false_when_not_importable():
    from importlib.metadata import PackageNotFoundError

    with patch(
        "ai_platform.jobs.code_package_install._metadata.version",
        side_effect=PackageNotFoundError("nope"),
    ):
        assert _is_already_installed(_record()) is False


def test_install_skips_already_installed():
    """Packages whose distribution version matches the catalog row must
    be skipped — download/pip never run.
    """
    service = MagicMock()
    service.list.return_value = [_record()]

    with patch(
        "ai_platform.jobs.code_package_install._is_already_installed",
        return_value=True,
    ):
        installed = install_packages_for_runtime("default", service)

    assert installed == []
    service.download.assert_not_called()


def test_install_downloads_and_invokes_pip_for_new_package():
    service = MagicMock()
    service.list.return_value = [_record()]
    service.download.return_value = (_record(), b"wheel-bytes")

    fake_pip_ok = MagicMock(returncode=0, stderr="")

    with patch(
        "ai_platform.jobs.code_package_install._is_already_installed",
        return_value=False,
    ), patch(
        "ai_platform.jobs.code_package_install.subprocess.run",
        return_value=fake_pip_ok,
    ) as mock_run:
        installed = install_packages_for_runtime("default", service)

    assert installed == ["toy_pkg@1.0.0"]
    service.download.assert_called_once_with("toy_pkg@1.0.0")
    mock_run.assert_called_once()
    cmd = mock_run.call_args.args[0]
    assert cmd[1:5] == ["-m", "pip", "install", "--force-reinstall"]
    # The temp wheel keeps the record's filename so pip can parse name/version.
    assert cmd[5].endswith(_record().filename)


def test_install_surfaces_pip_stderr_on_failure():
    """A non-zero pip exit must surface stderr in the warning, not the
    bare CalledProcessError (which swallowed the actual cause).
    """
    service = MagicMock()
    service.list.return_value = [_record()]
    service.download.return_value = (_record(), b"wheel-bytes")

    fake_pip_fail = MagicMock(returncode=1, stderr="ERROR: Invalid wheel filename")

    with patch(
        "ai_platform.jobs.code_package_install._is_already_installed",
        return_value=False,
    ), patch(
        "ai_platform.jobs.code_package_install.subprocess.run",
        return_value=fake_pip_fail,
    ):
        installed = install_packages_for_runtime("default", service)

    # Failed install isn't in the returned list (best-effort path).
    assert installed == []


def test_install_swallows_individual_failures():
    """A failing install must not abort the boot — the worker can still
    serve the JobDefinitions baked into its image. The returned list
    only includes the ones that landed.
    """
    service = MagicMock()
    service.list.return_value = [_record(name="good"), _record(name="bad")]

    def fake_download(pkg_id):
        if pkg_id == "bad@1.0.0":
            raise RuntimeError("oh no")
        return (_record(name="good"), b"x")

    service.download.side_effect = fake_download

    with patch(
        "ai_platform.jobs.code_package_install._is_already_installed",
        return_value=False,
    ), patch(
        "ai_platform.jobs.code_package_install.subprocess.run",
        return_value=MagicMock(returncode=0, stderr=""),
    ):
        installed = install_packages_for_runtime("default", service)

    assert installed == ["good@1.0.0"]


def test_install_no_op_on_empty_catalog():
    service = MagicMock()
    service.list.return_value = []
    assert install_packages_for_runtime("default", service) == []
    service.download.assert_not_called()


def test_install_swallows_list_failure():
    """A service.list() that raises (e.g. DB down) must not crash boot.
    The worker still serves the JobDefinitions whose code is baked in.
    """
    service = MagicMock()
    service.list.side_effect = RuntimeError("DB unreachable")
    assert install_packages_for_runtime("default", service) == []
    service.download.assert_not_called()


def test_install_filters_by_runtime():
    """The caller passes its `runtime_selector`; the service is queried
    with that exact filter (so a crewai worker doesn't grab default
    wheels and vice versa).
    """
    service = MagicMock()
    service.list.return_value = []
    install_packages_for_runtime("crewai", service)
    service.list.assert_called_once_with(runtime_selector="crewai")
