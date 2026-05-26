"""Platform-enforced plane boundary — fail loud, don't trust the developer.

The control plane (the API process) must never import the execution engine
(`pydantic_graph`, `crewai`). Convention isn't enough: one stray
`from mathai.<domain>.workflow import ...` in a `control.py` would silently
drag the engine — and its runtime dependency conflict — back into the API.

So the platform *blocks* it. This installs a `sys.meta_path` finder that
raises on a denylist of modules. The API entrypoint arms it **before**
importing any domain control module; if a control module (or anything it
pulls, transitively) imports the engine, the process dies at import time
with the offending module named. It is intentionally blunt — there is no
way for a developer to "just import it anyway."

This is the enforcement half of the control/execution split
(docs/control_execution_split.md). The execution plane (workers, the
descriptor generator) never arms the guard — it *is* the engine.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from importlib.abc import MetaPathFinder
from typing import Iterator

# Modules that must never load in a control-plane process. These are the two
# engine stacks; importing an execution module transitively pulls one of them,
# so naming the engines is enough to catch every leak path.
CONTROL_PLANE_DENYLIST: tuple[str, ...] = ("pydantic_graph", "crewai")


class ControlPlaneViolation(ImportError):
    """Raised when a control-plane process tries to import the engine."""


class _DenyFinder(MetaPathFinder):
    def __init__(self, denied: tuple[str, ...]):
        self._denied = denied

    def find_spec(self, fullname, path, target=None):  # noqa: D401
        for denied in self._denied:
            if fullname == denied or fullname.startswith(denied + "."):
                raise ControlPlaneViolation(
                    f"control plane tried to import '{fullname}', which is "
                    f"execution-only (denied root: '{denied}'). The "
                    f"control/execution boundary is platform-enforced — move "
                    f"engine imports into the domain's execution.py, never "
                    f"control.py. See docs/control_execution_split.md."
                )
        return None  # not our concern → defer to the real finders


_armed: _DenyFinder | None = None


def enforce_control_plane(extra_denied: tuple[str, ...] = ()) -> None:
    """Arm the guard in this process (idempotent). Call it as early as
    possible in a control-plane entrypoint — before importing any domain."""
    global _armed
    if _armed is not None:
        return
    _armed = _DenyFinder(CONTROL_PLANE_DENYLIST + tuple(extra_denied))
    sys.meta_path.insert(0, _armed)


@contextmanager
def control_plane_guard(extra_denied: tuple[str, ...] = ()) -> Iterator[_DenyFinder]:
    """Scoped guard for tests — arms on enter, disarms on exit.

    Note: Python short-circuits imports already in `sys.modules`, so this
    only blocks *fresh* imports. Tests that need a guaranteed-clean check
    should run in a subprocess.
    """
    finder = _DenyFinder(CONTROL_PLANE_DENYLIST + tuple(extra_denied))
    sys.meta_path.insert(0, finder)
    try:
        yield finder
    finally:
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
