"""Celery boot-time CodePackage install split (issue #73, epic #64).

The prefork pool bug: `install_packages_for_runtime` used to run in
`worker_process_init`, which fires once per forked child. With
`CELERY_CONCURRENCY>=2`, N children pip-installed the same wheels into the same
`site-packages` concurrently — corrupting each other (the classic
`google/_upb/` missing-file error) and leaving children with inconsistent
domain registration (one child `serving: [math_notes]`, another
`[math_notes, math_qa]`). A job could land on a child that can't run it.

The fix hoists the install to `worker_init` (the worker's MAIN process, fired
once before the prefork), keeping only the per-child psycopg-pool bootstrap +
domain registration in `worker_process_init`. These tests pin that split:

- the install hook is wired to `worker_init`, runs the install exactly once,
  scoped to this pool's runtime;
- it closes the transient catalog DB pool before returning, so no socket is
  inherited across the fork (the reason the per-child bootstrap exists);
- the per-child handler `_init_worker` no longer installs anything.

No live broker / DB is needed — the handlers are plain functions; their
dependencies are monkeypatched.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


@pytest.fixture
def celery_app(monkeypatch):
    """Import the celery app module with a broker URL set (it reads
    `CELERY_BROKER_URL` at import time to build `app`)."""
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    return importlib.import_module("ai_platform.entrypoints.celery_app")


class _Pool:
    """Stand-in for the supabase backend's psycopg `ConnectionPool` — records
    whether it was closed before the (hypothetical) fork."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _fake_backend(pool: _Pool | None) -> SimpleNamespace:
    backend = SimpleNamespace(code_package_repo=object(), file_repo=object())
    if pool is not None:
        backend._pool = pool
    return backend


# ---------------------------------------------------------------------------
# worker_init: install once, in the main process, scoped to the runtime
# ---------------------------------------------------------------------------

def _receiver_names(signal) -> set[str]:
    """Names of the functions connected to a celery signal. Celery stores
    receivers as weakrefs, so dereference before reading `__name__`."""
    import weakref

    names: set[str] = set()
    for _key, rcv in signal.receivers:
        fn = rcv() if isinstance(rcv, weakref.ReferenceType) else rcv
        if fn is not None:
            names.add(fn.__name__)
    return names


def test_install_hook_is_wired_to_worker_init(celery_app):
    """The install must fire on `worker_init` (main process, pre-fork), NOT on
    `worker_process_init` (per child) — that wiring is the whole #73 fix."""
    from celery.signals import worker_init, worker_process_init

    assert "_install_runtime_packages" in _receiver_names(worker_init)
    assert "_install_runtime_packages" not in _receiver_names(worker_process_init)
    # The per-child handler stays put (it opens this child's own psycopg pool).
    assert "_init_worker" in _receiver_names(worker_process_init)


def test_install_runs_once_scoped_to_runtime(celery_app, monkeypatch):
    """`_install_runtime_packages` installs exactly once for THIS pool's
    runtime — mirroring the producer/consumer per-runtime scope (#66)."""
    pool = _Pool()
    monkeypatch.setattr(celery_app, "make_backend", lambda: _fake_backend(pool))
    monkeypatch.setattr(celery_app, "CodePackageService", lambda *a, **k: object())

    calls: list[str] = []
    monkeypatch.setattr(
        celery_app,
        "install_packages_for_runtime",
        lambda runtime, service: calls.append(runtime) or ["mathai-math-qa@0.1.1"],
    )

    celery_app._install_runtime_packages()

    assert calls == [celery_app.RUNTIME]


def test_install_closes_catalog_pool_before_fork(celery_app, monkeypatch):
    """Fork-safety: the transient pool opened to read the catalog is closed
    before the hook returns, so its connection FDs are not inherited across the
    prefork fork (which is exactly what hangs the children — see module
    docstring on per-child bootstrap)."""
    pool = _Pool()
    monkeypatch.setattr(celery_app, "make_backend", lambda: _fake_backend(pool))
    monkeypatch.setattr(celery_app, "CodePackageService", lambda *a, **k: object())
    monkeypatch.setattr(
        celery_app, "install_packages_for_runtime", lambda runtime, service: []
    )

    celery_app._install_runtime_packages()

    assert pool.closed is True


def test_install_closes_pool_even_when_install_raises(celery_app, monkeypatch):
    """The pool close lives in a `finally` — a blow-up mid-install must not leak
    a connection FD into the fork."""
    pool = _Pool()
    monkeypatch.setattr(celery_app, "make_backend", lambda: _fake_backend(pool))
    monkeypatch.setattr(celery_app, "CodePackageService", lambda *a, **k: object())

    def boom(runtime, service):
        raise RuntimeError("catalog exploded")

    monkeypatch.setattr(celery_app, "install_packages_for_runtime", boom)

    with pytest.raises(RuntimeError):
        celery_app._install_runtime_packages()

    assert pool.closed is True


def test_install_no_pool_backend_is_noop(celery_app, monkeypatch):
    """The local / b2 backends expose no `_pool`; the close must degrade to a
    no-op rather than raising (`getattr(..., None)`)."""
    monkeypatch.setattr(celery_app, "make_backend", lambda: _fake_backend(None))
    monkeypatch.setattr(celery_app, "CodePackageService", lambda *a, **k: object())
    monkeypatch.setattr(
        celery_app, "install_packages_for_runtime", lambda runtime, service: []
    )

    # Must not raise even though the backend has no `_pool`.
    celery_app._install_runtime_packages()


# ---------------------------------------------------------------------------
# worker_process_init: still per-child, but NO LONGER installs
# ---------------------------------------------------------------------------

def test_per_child_bootstrap_does_not_install(celery_app, monkeypatch):
    """`_init_worker` (per prefork child) registers domains by importing the
    already-installed wheels, but must NOT call `install_packages_for_runtime`
    itself — that per-child install is the race #73 removes. It still bootstraps
    this child's own workspace (psycopg pool)."""
    bootstrapped: list[bool] = []

    fake_ws = SimpleNamespace(
        code_package_service=object(),
        job_definition_service=object(),
    )

    def fake_bootstrap():
        bootstrapped.append(True)
        return fake_ws

    install_calls: list[str] = []

    monkeypatch.setattr(celery_app, "bootstrap_workspace", fake_bootstrap)
    monkeypatch.setattr(
        celery_app,
        "install_packages_for_runtime",
        lambda runtime, service: install_calls.append(runtime) or [],
    )
    monkeypatch.setattr(
        celery_app, "execution_registers_from_catalog", lambda svc, runtime: ["reg"]
    )
    monkeypatch.setattr(
        celery_app,
        "register_execution_domains",
        lambda registers, ws: SimpleNamespace(job_executions={"math_qa": object()}),
    )

    celery_app._init_worker()

    # Per-child workspace bootstrap still happens (own psycopg pool)…
    assert bootstrapped == [True]
    # …but the install does NOT — that's hoisted to the main process (#73).
    assert install_calls == []
    # Domains are registered for this child.
    assert celery_app._domains is not None
    assert "math_qa" in celery_app._domains.job_executions
