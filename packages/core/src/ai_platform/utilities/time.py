"""Centralised UTC clock helper.

A single `utc_now()` so future test-time control (freezegun, mocking,
recorded time travel for backtests) lives in one place. Every record
default factory + every `datetime.now(timezone.utc)` call in the
platform passes through here.

Don't import `datetime.utcnow` anywhere — it's deprecated since 3.12
and returns a *naive* timestamp which silently corrupts comparisons
across timezones.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Tz-aware UTC `datetime` for *now*. Single source of truth."""
    return datetime.now(timezone.utc)
