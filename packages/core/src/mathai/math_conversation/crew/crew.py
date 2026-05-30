"""Multi-persona panel builder for math_conversation.

Replaces the single-agent micro builder (see `crew_builder.py`). A
panel is *not* one CrewAI Crew with N sequential tasks: that shape
can't early-exit when a panelist calls `conclude`. Instead,
`RunCrewStep` owns a Python loop and constructs one single-agent /
single-task Crew per turn; this module supplies the prebuilt panel
(agents + signals + display metadata) and the per-turn `Crew` factory.

Transcript handling: each turn's task description embeds the running
transcript so the agent has full context. The transcript is a simple
`[Role]\\ncontent` block per turn — round-trippable, human-readable,
and what the model already sees in chat-completion form.

Turn ordering is round-robin in v1; a single conductor / picker prompt
is a follow-up the design doc names explicitly. The personae order is
fixed in `DEFAULT_PANEL` and can be overridden via `build_panel(...)`.

CrewAI is imported lazily — only `build_turn_crew` triggers the import,
keeping the rest of the module safe to import from any runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from mathai.math_conversation.crew.personae import build_agent
from mathai.math_conversation.crew.tools import ConcludeSignal, build_conclude_tool
from mathai.math_conversation.registry import load_persona

# v1 panel composition. The Algebraist anchors rigor, the Visualist
# pushes intuition, the Synthesist closes loops between them.
DEFAULT_PANEL: tuple[str, ...] = ("algebraist", "visualist", "synthesist")


@dataclass
class Panel:
    """Materialized panel for one conversation run.

    Holds the prebuilt agents (one per persona name), the shared
    `ConcludeSignal` (any agent's `conclude` call flips it), and the
    resolved display metadata indexed by persona name. The turn loop in
    `RunCrewStep` picks the next agent by `order[turn_index %
    len(order)]` and constructs a fresh single-task Crew per turn via
    `build_turn_crew`.
    """

    agents_by_name: dict[str, Any]      # persona_name -> crewai.Agent
    display_by_name: dict[str, str]     # persona_name -> display_name
    role_by_name: dict[str, str]        # persona_name -> role
    conclude_signal: ConcludeSignal
    order: tuple[str, ...]              # persona names in round-robin order


def build_panel(personae: tuple[str, ...] = DEFAULT_PANEL) -> Panel:
    """Construct a `Panel`: one agent per persona, sharing one conclude signal.

    All agents receive the same `conclude` tool instance, so a call from
    any panelist flips the same signal the turn loop reads.
    """
    signal = ConcludeSignal()
    conclude_tool = build_conclude_tool(signal)
    tools_by_name: dict[str, Any] = {"conclude": conclude_tool}

    agents_by_name: dict[str, Any] = {}
    display_by_name: dict[str, str] = {}
    role_by_name: dict[str, str] = {}
    for name in personae:
        spec = load_persona(name)
        agents_by_name[name] = build_agent(name, tools_by_name=tools_by_name)
        display_by_name[name] = spec.display_name
        role_by_name[name] = spec.role

    return Panel(
        agents_by_name=agents_by_name,
        display_by_name=display_by_name,
        role_by_name=role_by_name,
        conclude_signal=signal,
        order=personae,
    )


def append_to_transcript(transcript: str, role: str, content: str) -> str:
    """Append `[role]\\ncontent` to `transcript`, separated by a blank line."""
    block = f"[{role}]\n{content.strip()}"
    return f"{transcript}\n\n{block}" if transcript.strip() else block


def build_task_description(
    role: str,
    seed_question: str,
    transcript: str,
    seed_context: Optional[dict] = None,
) -> str:
    """Compose the per-turn task description for `role`.

    Always includes the seed question. When `seed_context` carries
    fields from a prior math_qa job (answer / latex), they're included
    so the panel can react to and refine that single-shot answer rather
    than start from scratch. The transcript is omitted on turn 1
    (empty), included from turn 2 onward.
    """
    parts = [
        f"You are the {role} on a small panel discussing a math problem.",
        "",
        f"Seed question:\n{seed_question}",
    ]
    if seed_context:
        prior_answer = seed_context.get("answer")
        prior_latex = seed_context.get("latex")
        if prior_answer:
            parts.extend([
                "",
                "A prior single-shot answer to react to (not authoritative — "
                "build on it, refine it, or push back):",
                prior_answer,
            ])
        if prior_latex:
            parts.extend(["", "LaTeX of the prior answer:", prior_latex])
    if transcript.strip():
        parts.extend(["", "Conversation so far:", transcript])
    parts.extend([
        "",
        f"It is your turn. Contribute ONE focused point as the {role}.",
        "If the panel has covered the ground and there is nothing new to add, "
        "call the `conclude` tool with a short reason instead of speaking.",
    ])
    return "\n".join(parts)


def build_turn_crew(
    panel: Panel,
    persona_name: str,
    transcript: str,
    seed_question: str,
    *,
    seed_context: Optional[dict] = None,
) -> Any:
    """Return a one-agent, one-task `crewai.Crew` for the next turn.

    The agent is `panel.agents_by_name[persona_name]`; the task is built
    by `build_task_description`. `memory=False` keeps each conversation
    hermetic (design decision in `docs/math_conversation.md`).
    """
    import crewai

    agent = panel.agents_by_name[persona_name]
    role = panel.role_by_name[persona_name]
    task = crewai.Task(
        description=build_task_description(role, seed_question, transcript, seed_context=seed_context),
        expected_output=(
            "Your contribution to the panel, in your voice. One focused "
            "point. If the discussion has fully covered the ground, call "
            "the `conclude` tool with a short reason instead."
        ),
        agent=agent,
    )
    return crewai.Crew(agents=[agent], tasks=[task], memory=False, verbose=False)
