"""Unit tests for `make_pool` hardening (issue #57).

A stale Supabase-pooler connection used to block `psycopg.wait` with no
timeout, wedging a single-job poll worker forever. `make_pool` now sets a
statement timeout, a connect timeout, TCP keepalives, and a checkout
health-check. These tests capture the pool constructor args (no live DB)
to pin that the hardening is actually applied.
"""
from __future__ import annotations

import pytest

import ai_platform.workspace.storage.structured.supabase as sb

_CONN = "postgresql://user:secret@db.example:5432/postgres"


class _FakePool:
    """Captures ConnectionPool(...) args instead of opening a real pool."""

    last: dict | None = None

    def __init__(self, conninfo="", *, kwargs=None, min_size=1, max_size=4,
                 open=True, check=None):
        _FakePool.last = {
            "conninfo": conninfo,
            "kwargs": kwargs,
            "min_size": min_size,
            "max_size": max_size,
            "open": open,
            "check": check,
        }

    @staticmethod
    def check_connection(conn):  # referenced as the default `check`
        return None


@pytest.fixture
def captured(monkeypatch):
    monkeypatch.setattr(sb, "ConnectionPool", _FakePool)
    _FakePool.last = None
    return _FakePool


def test_pool_sets_statement_and_connect_timeouts(captured):
    sb.make_pool(_CONN)
    kw = captured.last["kwargs"]
    assert kw["connect_timeout"] == 10
    assert "-c statement_timeout=30000" in kw["options"]
    # Connection params still come through.
    assert kw["host"] == "db.example"
    assert kw["dbname"] == "postgres"
    assert kw["user"] == "user"


def test_pool_enables_tcp_keepalives(captured):
    sb.make_pool(_CONN)
    kw = captured.last["kwargs"]
    assert kw["keepalives"] == 1
    assert kw["keepalives_idle"] == 30
    assert kw["keepalives_interval"] == 10
    assert kw["keepalives_count"] == 3


def test_pool_registers_checkout_health_check(captured):
    sb.make_pool(_CONN)
    # A dead connection is recycled on checkout rather than handed to a caller.
    assert captured.last["check"] is _FakePool.check_connection


def test_statement_timeout_is_configurable(captured):
    sb.make_pool(_CONN, statement_timeout_ms=5000, connect_timeout=3)
    kw = captured.last["kwargs"]
    assert "-c statement_timeout=5000" in kw["options"]
    assert kw["connect_timeout"] == 3


def test_schema_scoping_preserved_alongside_timeout(captured):
    sb.make_pool(_CONN, schema="integration_tests")
    opts = captured.last["kwargs"]["options"]
    assert "-c search_path=integration_tests" in opts
    assert "-c statement_timeout=30000" in opts


def test_no_schema_means_no_search_path(captured):
    sb.make_pool(_CONN)
    assert "search_path" not in captured.last["kwargs"]["options"]
