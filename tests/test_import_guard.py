"""The platform-enforced control/execution boundary.

The control plane (API) must not import the engine. `import_guard` blocks it
at the import system level — these tests prove it both *allows* the real
control plane and *blocks* the engine, in a guaranteed-fresh interpreter
(subprocess), since Python short-circuits already-imported modules.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ai_platform.jobs.import_guard import (
    ControlPlaneViolation,
    _DenyFinder,
)

_SRC = Path(__file__).resolve().parents[1] / "src"


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_SRC.parent),
        env={"PYTHONPATH": str(_SRC), "PATH": __import__("os").environ.get("PATH", "")},
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Finder unit behavior
# ---------------------------------------------------------------------------

def test_finder_blocks_denied_root_and_submodules():
    f = _DenyFinder(("pydantic_graph", "crewai"))
    for name in ("pydantic_graph", "pydantic_graph.nodes", "crewai", "crewai.llm"):
        with pytest.raises(ControlPlaneViolation):
            f.find_spec(name, None)


def test_finder_allows_unrelated_modules():
    f = _DenyFinder(("pydantic_graph", "crewai"))
    # Real allowed deps, and a name that merely shares a prefix (not the root).
    for name in ("pydantic", "fastapi", "pydantic_graphql"):
        assert f.find_spec(name, None) is None


# ---------------------------------------------------------------------------
# End-to-end enforcement (fresh interpreter)
# ---------------------------------------------------------------------------

def test_guard_allows_the_control_plane():
    """Arming the guard then importing every domain's control plane must
    succeed — proves the control plane is genuinely engine-free."""
    code = (
        "from ai_platform.jobs.import_guard import enforce_control_plane\n"
        "enforce_control_plane()\n"
        "import importlib, sys\n"
        "for m in ('mathai.math_qa.control', 'mathai.math_conversation.control'):\n"
        "    importlib.import_module(m)\n"
        "assert 'pydantic_graph' not in sys.modules\n"
        "assert 'crewai' not in sys.modules\n"
        "print('CONTROL_OK')\n"
    )
    proc = _run(code)
    assert proc.returncode == 0, proc.stderr
    assert "CONTROL_OK" in proc.stdout


def test_guard_blocks_the_engine():
    """Arming the guard then importing an execution module must crash with a
    ControlPlaneViolation — the engine cannot sneak into a control process."""
    code = (
        "from ai_platform.jobs.import_guard import enforce_control_plane\n"
        "enforce_control_plane()\n"
        "import importlib\n"
        "importlib.import_module('mathai.math_qa.execution')\n"
    )
    proc = _run(code)
    assert proc.returncode != 0
    assert "ControlPlaneViolation" in proc.stderr
    assert "control plane tried to import" in proc.stderr


def test_api_entrypoint_boots_under_the_guard(tmp_path: Path):
    """The real API entrypoint arms the guard and imports the control plane;
    importing it must not trip the guard (regression canary for leaks)."""
    code = (
        "import mathapp.entrypoints.api as api\n"
        "assert api.app is not None\n"
        "print('API_OK')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_SRC.parent),
        env={
            "PYTHONPATH": str(_SRC),
            "PATH": __import__("os").environ.get("PATH", ""),
            "BACKEND": "local",
            "LOCAL_DATA_DIR": str(tmp_path),
        },
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "API_OK" in proc.stdout
