"""Regression test for issue #45.

`structured.supabase` used to resolve its migrations directory at module
top level:

    _MIGRATIONS_DIR = find_ancestor_containing("supabase") / "supabase" / "migrations"

`find_ancestor_containing` walks up from the module's own `__file__`
looking for an ancestor dir that contains `supabase/`. That only exists
in the monorepo source layout; a wheel installed into `site-packages`
has no such ancestor, so the walk raised `RuntimeError` *at import*.
Because the CLI imports a domain's control module — which transitively
pulls in this module — any standalone `pip install aiplatform-core`
import of the control plane crashed.

The fix defers the walk to `_migrations_dir()`, called only when
migrations actually run. These tests pin that behavior so the
module-level walk can't sneak back.
"""
from __future__ import annotations

import importlib
import sys

import pytest

import ai_platform.utilities.paths as paths_mod

_MODNAME = "ai_platform.workspace.storage.structured.supabase"


def test_module_imports_when_ancestor_walk_would_fail():
    """Simulate a standalone wheel (no ancestor `supabase/` dir) by
    making the walk raise, then re-import the module. Import must
    succeed — the walk is no longer performed at module top level.
    """
    real = paths_mod.find_ancestor_containing

    def _boom(marker, start=None):
        raise RuntimeError(f"could not find an ancestor containing {marker!r}")

    paths_mod.find_ancestor_containing = _boom
    try:
        sys.modules.pop(_MODNAME, None)
        mod = importlib.import_module(_MODNAME)  # must NOT raise
        # The walk is deferred — it only fires when migrations run, and
        # only then would it raise on a real standalone install.
        with pytest.raises(RuntimeError):
            mod._migrations_dir()
    finally:
        paths_mod.find_ancestor_containing = real
        # Restore a clean module for any later importer.
        sys.modules.pop(_MODNAME, None)
        importlib.import_module(_MODNAME)


def test_migrations_dir_resolves_in_source_layout():
    """In the monorepo checkout the ancestor `supabase/` dir does exist,
    so the lazy resolver returns a real path ending in
    `supabase/migrations`.
    """
    mod = importlib.import_module(_MODNAME)
    path = mod._migrations_dir()
    assert path.name == "migrations"
    assert path.parent.name == "supabase"
