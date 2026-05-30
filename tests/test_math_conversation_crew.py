"""Unit tests for the conclude tool — the closure-captured signal that
lets a panelist short-circuit the brainstorm loop.

CrewAI-free: exercises the pure-Python runner built by
`_make_conclude_runner` without importing `crewai`. The
crewai-dependent wrapper (`build_conclude_tool`) is exercised
indirectly via the workflow tests once the panel + turn loop land.
"""
from __future__ import annotations

from mathai.math_conversation.crew.tools import (
    ConcludeSignal,
    _make_conclude_runner,
)


def test_conclude_runner_flips_signal_with_reason():
    signal = ConcludeSignal()
    run = _make_conclude_runner(signal)
    result = run("we've covered the ground")
    assert signal.fired is True
    assert signal.reason == "we've covered the ground"
    assert "we've covered the ground" in result


def test_conclude_runner_handles_empty_reason():
    """The tool's args schema defaults `reason` to "" — the runner must
    not crash on the empty string and should still flip the signal.
    """
    signal = ConcludeSignal()
    run = _make_conclude_runner(signal)
    result = run("")
    assert signal.fired is True
    assert signal.reason == ""
    assert result == "Concluded."


def test_conclude_runner_two_calls_keep_last_reason():
    """Defensive: if some pathological agent calls conclude twice, the
    signal stays fired and `reason` reflects the most recent call.
    """
    signal = ConcludeSignal()
    run = _make_conclude_runner(signal)
    run("first")
    run("second")
    assert signal.fired is True
    assert signal.reason == "second"


def test_concludesignal_independent_per_panel():
    """Each panel run constructs its own signal — sharing one would
    leak a prior run's conclude into the next.
    """
    a, b = ConcludeSignal(), ConcludeSignal()
    _make_conclude_runner(a)("done")
    assert a.fired and not b.fired
