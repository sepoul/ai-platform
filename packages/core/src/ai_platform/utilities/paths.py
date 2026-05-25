"""Locate repo-root data directories independent of package depth.

`instructions/` and `supabase/migrations/` live at the repo root, not inside
any package. After the control/execution package split, modules sit at
`packages/<pkg>/src/...`, so a hardcoded `parents[N]` no longer reaches the
root. Walk up to the ancestor that actually contains the marker instead.
"""
from __future__ import annotations

from pathlib import Path


def find_ancestor_containing(marker: str, start: Path | None = None) -> Path:
    """Return the nearest ancestor directory of `start` that contains `marker`.

    `start` defaults to this module's location. Raises if no ancestor has it.
    """
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        if (parent / marker).exists():
            return parent
    raise RuntimeError(f"could not find an ancestor containing {marker!r} from {here}")
