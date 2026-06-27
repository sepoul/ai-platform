"""Tests for catalog-driven import discovery (Phase 1 of the repo
split). Covers the two helpers in `composition_root`:

- `control_registers_from_catalog(jd_service)` reads JobDefinition
  rows and imports each unique `control_entrypoint`.
- `execution_registers_from_catalog(jd_service, runtime)` does the
  worker analog — filtered by runtime, imports each unique
  `code_entrypoint`.

The whole point of these helpers is to drop
`composition_root._DOMAINS` after the repo split. The behaviors that
matter:

- Dedup by entrypoint string (one row per JobControl, but multiple
  rows of the same domain share the same entrypoint — we only want
  to import the module once).
- Skip rows whose entrypoint is empty (backward-compat with
  pre-Phase-1 rows; they're overwritten on next deploy).
- Skip rows whose entrypoint can't be imported (best-effort: log +
  continue, return what worked). Mirror of the hardcoded helpers.
- Catalog-level failures (DB down) return [] so the caller can fall
  back to the hardcoded path without crashing boot.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from ai_platform.composition_root import (
    control_registers_from_catalog,
    execution_registers_from_catalog,
)
from ai_platform.workspace.storage.structured.job_definition_repository import (
    JobDefinitionRecord,
)


# ---------------------------------------------------------------------------
# Synthetic importable modules — pretend to be a deployed domain's
# control + execution modules. Registered on sys.modules in a fixture
# so importlib finds them when our helpers do their import.
# ---------------------------------------------------------------------------


def _make_module(module_name: str, attr_name: str) -> types.ModuleType:
    mod = types.ModuleType(module_name)
    sentinel = MagicMock(name=f"{module_name}:{attr_name}")
    setattr(mod, attr_name, sentinel)
    return mod


@pytest.fixture
def fake_domain_modules():
    """Register two synthetic domain modules on sys.modules.

    Names chosen to not collide with real modules. The fixture also
    yields the sentinel callables so tests can assert identity.
    """
    a_control = _make_module("syntheticdomain.a.control", "register_control")
    a_execution = _make_module("syntheticdomain.a.execution", "register_execution")
    b_control = _make_module("syntheticdomain.b.control", "register_control")
    b_execution = _make_module("syntheticdomain.b.execution", "register_execution")

    # importlib walks the package hierarchy, so register the parents too.
    for name in (
        "syntheticdomain",
        "syntheticdomain.a",
        "syntheticdomain.b",
    ):
        sys.modules.setdefault(name, types.ModuleType(name))

    sys.modules["syntheticdomain.a.control"] = a_control
    sys.modules["syntheticdomain.a.execution"] = a_execution
    sys.modules["syntheticdomain.b.control"] = b_control
    sys.modules["syntheticdomain.b.execution"] = b_execution

    yield {
        "a_control": a_control.register_control,
        "a_execution": a_execution.register_execution,
        "b_control": b_control.register_control,
        "b_execution": b_execution.register_execution,
    }

    for name in [
        "syntheticdomain",
        "syntheticdomain.a",
        "syntheticdomain.b",
        "syntheticdomain.a.control",
        "syntheticdomain.a.execution",
        "syntheticdomain.b.control",
        "syntheticdomain.b.execution",
    ]:
        sys.modules.pop(name, None)


def _record(
    name: str,
    *,
    runtime: str = "default",
    control_entrypoint: str = "",
    code_entrypoint: str = "",
    version: str = "1.0.0",
) -> JobDefinitionRecord:
    return JobDefinitionRecord(
        id=JobDefinitionRecord.make_id(name, version),
        name=name,
        version=version,
        runtime_selector=runtime,
        code_entrypoint=code_entrypoint,
        control_entrypoint=control_entrypoint,
    )


# ---------------------------------------------------------------------------
# control_registers_from_catalog
# ---------------------------------------------------------------------------


def test_control_from_catalog_imports_each_unique_entrypoint(fake_domain_modules):
    svc = MagicMock()
    svc.list.return_value = [
        _record("a1", control_entrypoint="syntheticdomain.a.control:register_control"),
        _record("b1", control_entrypoint="syntheticdomain.b.control:register_control"),
    ]
    out = control_registers_from_catalog(svc)
    assert set(out) == {fake_domain_modules["a_control"], fake_domain_modules["b_control"]}


def test_control_from_catalog_dedups_by_entrypoint(fake_domain_modules):
    """Two JobDefinitions from the same domain shouldn't double-import."""
    svc = MagicMock()
    svc.list.return_value = [
        _record("a1", control_entrypoint="syntheticdomain.a.control:register_control"),
        _record("a2", control_entrypoint="syntheticdomain.a.control:register_control"),
    ]
    out = control_registers_from_catalog(svc)
    assert out == [fake_domain_modules["a_control"]]


def test_control_from_catalog_skips_empty_entrypoint(fake_domain_modules):
    """Pre-Phase-1 rows with empty control_entrypoint must be skipped,
    not raise — they'll be overwritten by the next deploy.
    """
    svc = MagicMock()
    svc.list.return_value = [
        _record("a1", control_entrypoint=""),
        _record("b1", control_entrypoint="syntheticdomain.b.control:register_control"),
    ]
    out = control_registers_from_catalog(svc)
    assert out == [fake_domain_modules["b_control"]]


def test_control_from_catalog_skips_unimportable_entrypoint(fake_domain_modules):
    svc = MagicMock()
    svc.list.return_value = [
        _record("ghost", control_entrypoint="no.such.module:register_control"),
        _record("real", control_entrypoint="syntheticdomain.a.control:register_control"),
    ]
    out = control_registers_from_catalog(svc)
    assert out == [fake_domain_modules["a_control"]]


def test_control_from_catalog_returns_empty_on_list_failure():
    """A DB-down list() must return [] so the caller can fall back to
    the hardcoded path, not crash boot.
    """
    svc = MagicMock()
    svc.list.side_effect = RuntimeError("DB down")
    assert control_registers_from_catalog(svc) == []


def test_control_from_catalog_rejects_malformed_entrypoint(fake_domain_modules):
    """An entrypoint missing the `module:callable` shape doesn't crash —
    it's logged + skipped like an import failure.
    """
    svc = MagicMock()
    svc.list.return_value = [
        _record("bad", control_entrypoint="missing_colon_separator"),
        _record("ok", control_entrypoint="syntheticdomain.a.control:register_control"),
    ]
    out = control_registers_from_catalog(svc)
    assert out == [fake_domain_modules["a_control"]]


# ---------------------------------------------------------------------------
# execution_registers_from_catalog
# ---------------------------------------------------------------------------


def test_execution_from_catalog_filters_by_runtime(fake_domain_modules):
    """Worker queries with the runtime as a parameter; only rows for
    that runtime get imported. Asserts the service-level filter is
    used, not in-Python.
    """
    svc = MagicMock()
    svc.list.return_value = [
        _record(
            "a",
            runtime="default",
            code_entrypoint="syntheticdomain.a.execution:register_execution",
        ),
    ]
    out = execution_registers_from_catalog(svc, "default")
    svc.list.assert_called_once_with(runtime_selector="default")
    assert out == [fake_domain_modules["a_execution"]]


def test_execution_from_catalog_dedups(fake_domain_modules):
    svc = MagicMock()
    svc.list.return_value = [
        _record(
            "a1",
            code_entrypoint="syntheticdomain.a.execution:register_execution",
        ),
        _record(
            "a2",
            code_entrypoint="syntheticdomain.a.execution:register_execution",
        ),
    ]
    out = execution_registers_from_catalog(svc, "default")
    assert out == [fake_domain_modules["a_execution"]]


def test_execution_from_catalog_returns_empty_on_list_failure():
    svc = MagicMock()
    svc.list.side_effect = RuntimeError("DB down")
    assert execution_registers_from_catalog(svc, "default") == []


# ---------------------------------------------------------------------------
# One bad domain must not take down the rest (issue #46). A domain whose
# module raises at import — with *any* exception, not just the narrow
# ModuleNotFoundError/AttributeError/ValueError set — must be logged and
# skipped, while every other domain on the runtime keeps registering.
# ---------------------------------------------------------------------------


@pytest.fixture
def exploding_domain_module():
    """Register a parent package + a module that raises a non-narrow
    exception (TypeError) when imported, mimicking an incompatible-dep
    break like the pydantic-graph 2.x `Graph.__init__()` regression.
    """
    name = "explodingdomain.execution"

    class _Boom(types.ModuleType):
        def __getattr__(self, attr):
            raise TypeError(
                "Graph.__init__() missing 8 required positional arguments"
            )

    sys.modules.setdefault("explodingdomain", types.ModuleType("explodingdomain"))
    sys.modules[name] = _Boom(name)
    yield "explodingdomain.execution:register_execution"
    sys.modules.pop(name, None)
    sys.modules.pop("explodingdomain", None)


@pytest.mark.parametrize(
    "registers_from_catalog, ep_kwarg, sentinel_key",
    [
        (control_registers_from_catalog, "control_entrypoint", "a_control"),
        (execution_registers_from_catalog, "code_entrypoint", "a_execution"),
    ],
)
def test_from_catalog_isolates_non_narrow_import_failure(
    fake_domain_modules,
    exploding_domain_module,
    registers_from_catalog,
    ep_kwarg,
    sentinel_key,
):
    """A domain whose import raises TypeError (outside the old narrow
    catch tuple) is skipped, not propagated — the healthy domain still
    registers. Before the fix this leaked out and crash-looped the
    whole runtime.
    """
    healthy_ep = (
        "syntheticdomain.a.control:register_control"
        if ep_kwarg == "control_entrypoint"
        else "syntheticdomain.a.execution:register_execution"
    )
    svc = MagicMock()
    svc.list.return_value = [
        _record("boom", **{ep_kwarg: exploding_domain_module}),
        _record("healthy", **{ep_kwarg: healthy_ep}),
    ]
    args = (svc,) if registers_from_catalog is control_registers_from_catalog else (svc, "default")
    out = registers_from_catalog(*args)
    assert out == [fake_domain_modules[sentinel_key]]
