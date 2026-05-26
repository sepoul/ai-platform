"""Build the CrewAI panel — micro version.

The full T5 builds a multi-persona panel with a `conclude` tool and a
turn loop. This micro version builds a SINGLE Algebraist agent with one
task ("respond to the seed question") so the worker proves end-to-end:
submit → crewai kickoff → ConversationTurn → MathConversationArtifact.

`crewai` is imported lazily — only callers in the crewai-runtime worker
trigger the import.
"""
from __future__ import annotations

from typing import Any

from mathai.math_conversation.crew.personae import build_agent


def build_micro_crew(seed_question: str, persona: str = "algebraist") -> Any:
    """Return a `crewai.Crew` with one agent + one task answering `seed_question`."""
    import crewai

    agent = build_agent(persona)
    task = crewai.Task(
        description=(
            "Read the seed question carefully and provide a concise, rigorous "
            "first-pass answer in your voice as " + persona + ".\n\n"
            f"Seed question:\n{seed_question}"
        ),
        expected_output="A short paragraph answering the seed question.",
        agent=agent,
    )
    return crewai.Crew(agents=[agent], tasks=[task], memory=False, verbose=False)
