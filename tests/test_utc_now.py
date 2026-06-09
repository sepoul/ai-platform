"""Tests for `ai_platform.utilities.time`.

The helper is one line, but it underpins every default factory on
every storage record + every log entry. Two invariants matter:

1. The returned datetime is timezone-aware (UTC). Naive timestamps
   silently corrupt comparisons across stored records and were a
   latent bug in two places before centralisation (see PR closing
   §5).
2. It's the single source of truth — no module re-defines its own
   `_utc_now` or calls `datetime.now(timezone.utc)` inline. We assert
   this via a grep-style check across `packages/`.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ai_platform.utilities.time import utc_now


def test_utc_now_is_tz_aware_utc():
    now = utc_now()
    assert isinstance(now, datetime)
    assert now.tzinfo is not None, "utc_now() must return tz-aware datetimes"
    assert now.utcoffset() == timezone.utc.utcoffset(now), (
        f"utc_now() offset is {now.utcoffset()}, expected UTC"
    )


def test_no_stray_naive_now_callsites():
    """No module under `packages/` may call `datetime.now()` (no args)
    or `datetime.utcnow()`. Both return naive timestamps and were the
    cause of two latent bugs in `ai/prompts/models.py` pre-centralisation.

    `datetime.now(timezone.utc)` is also banned — the centralised
    `utc_now()` is the single seam, so test-time control (freezegun
    etc.) only has to monkey-patch one place.
    """
    repo_root = Path(__file__).resolve().parent.parent
    # Walk only git-tracked .py files — skips stale .venv copies left
    # over from local dev (math-app moved out post §7q but a `.venv`
    # may linger) and other untracked junk.
    tracked = subprocess.run(
        ["git", "ls-files", "packages/**/*.py"],
        capture_output=True, text=True, cwd=repo_root, check=True,
    ).stdout.splitlines()

    offenders: list[str] = []
    forbidden_patterns = (
        "datetime.utcnow",
        "datetime.now(timezone",  # use utc_now() instead
        "default_factory=datetime.now",  # bare; returns naive
    )
    for relpath in tracked:
        if not relpath:
            continue
        # The single seam is allowed.
        if relpath.endswith("ai_platform/utilities/time.py"):
            continue
        # Test file itself contains the patterns as strings; skip it.
        if relpath.endswith("tests/test_utc_now.py"):
            continue
        path = repo_root / relpath
        text = path.read_text(encoding="utf-8")
        for pat in forbidden_patterns:
            if pat in text:
                offenders.append(f"{relpath} contains {pat!r}")
    assert not offenders, (
        "Found stray datetime.now-style calls — route them through "
        "ai_platform.utilities.time.utc_now() instead:\n  "
        + "\n  ".join(offenders)
    )
