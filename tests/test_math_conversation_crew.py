"""Unit tests for the crew helpers — tools, panel-build helpers, and
the per-turn task composition.

CrewAI-free: every test here exercises the pure-Python pieces of the
panel (the conclude signal closure, transcript appender, task description
builder) without importing `crewai`. The CrewAI-dependent paths
(`build_conclude_tool`, `build_agent`, `build_panel`,
`build_turn_crew`) are exercised via the workflow tests' `_patch_panel`
helper in `test_math_conversation.py`.
"""
from __future__ import annotations

from mathai.math_conversation.crew.crew import (
    DEFAULT_PANEL,
    append_to_transcript,
    build_task_description,
)
from mathai.math_conversation.crew.tools import (
    ConcludeSignal,
    _make_conclude_runner,
)


# ---------------------------------------------------------------------------
# conclude tool — closure-captured signal
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# transcript appender
# ---------------------------------------------------------------------------

def test_transcript_first_turn_has_no_leading_blank():
    out = append_to_transcript("", "Algebraist", "Define a group as...")
    assert out == "[Algebraist]\nDefine a group as..."


def test_transcript_appends_block_with_separator():
    t = append_to_transcript("", "Algebraist", "first")
    t = append_to_transcript(t, "Visualist", "second")
    assert t == "[Algebraist]\nfirst\n\n[Visualist]\nsecond"


def test_transcript_strips_content_whitespace():
    out = append_to_transcript("", "Algebraist", "  padded\n\n")
    assert out == "[Algebraist]\npadded"


def test_transcript_ignores_whitespace_only_prior():
    """Whitespace-only `transcript` is treated as empty (no separator)."""
    out = append_to_transcript("   \n\n", "Algebraist", "first")
    assert out == "[Algebraist]\nfirst"


# ---------------------------------------------------------------------------
# task description composition
# ---------------------------------------------------------------------------

def test_task_description_first_turn_omits_transcript_section():
    """The transcript is empty on turn 1; the task should not include a
    'Conversation so far:' section that would confuse the agent.
    """
    desc = build_task_description("Algebraist", "What is a group?", "")
    assert "What is a group?" in desc
    assert "Conversation so far" not in desc
    assert "Algebraist" in desc
    assert "conclude" in desc  # the polite-stop path is always advertised


def test_task_description_includes_running_transcript():
    transcript = "[Visualist]\nPicture symmetries of a square."
    desc = build_task_description("Algebraist", "What is D_4?", transcript)
    assert "Conversation so far" in desc
    assert "Picture symmetries" in desc
    assert "What is D_4?" in desc


def test_task_description_mentions_role_consistently():
    """The role appears in the opening framing and again in the call to
    action — the agent gets a clear "you are X, contribute as X" signal.
    """
    desc = build_task_description("Synthesist", "any question", "")
    # First line is the framing, last lines push the contribution + conclude path.
    first_line = desc.splitlines()[0]
    assert "Synthesist" in first_line
    assert desc.count("Synthesist") >= 2


# ---------------------------------------------------------------------------
# panel composition
# ---------------------------------------------------------------------------

def test_default_panel_is_three_named_personae():
    """The v1 design ships with three personae; the order is
    load-bearing (round-robin uses index % len) so a regression that
    silently changes it should fail loudly.
    """
    assert DEFAULT_PANEL == ("algebraist", "visualist", "synthesist")
