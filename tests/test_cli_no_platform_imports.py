"""The defining contract of aiplatform-cli (issue #49): importing it must
pull in **zero** platform internals — no `ai_platform`, no storage
backends, no domain. That's what lets it install standalone (`pipx`) and
dodge the import-time landmines that broke the in-core CLI (e.g. #45).

We check it in a clean subprocess (the pytest process already has
`ai_platform` loaded from other tests) with only the CLI's source on the
path. We assert nothing named `ai_platform*` ends up in `sys.modules`
after importing the whole CLI surface.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLI_SRC = _REPO_ROOT / "packages" / "cli" / "src"

_PROBE = """
import sys
# Import the entire CLI surface, including the entrypoint module.
import aiplatform_cli
import aiplatform_cli.config
import aiplatform_cli.api
import aiplatform_cli.deploy
import aiplatform_cli.cli

leaked = sorted(m for m in sys.modules if m == "ai_platform" or m.startswith("ai_platform."))
if leaked:
    print("LEAKED:" + ",".join(leaked))
    raise SystemExit(1)
print("CLEAN")
"""


def test_cli_imports_no_platform_internals():
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(_REPO_ROOT),
        env={"PYTHONPATH": str(_CLI_SRC), "PATH": __import__("os").environ.get("PATH", "")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "CLEAN" in result.stdout, result.stdout
