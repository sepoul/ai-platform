"""crewai-runtime smoke test — proves the worker[crewai] image runs CrewAI
on Anthropic, end to end, without going through the platform job system.

Use this to validate a fresh `worker-crewai` deploy before submitting a real
`math_conversation` job. Builds the same micro 1-agent crew that
`RunCrewStep` builds (Algebraist persona, Anthropic LLM via CrewAI's native
provider), kicks it off on a seed question, prints the agent's reply.

    docker compose --profile crewai run --rm worker-crewai \\
        python -m mathapp.entrypoints.crewai_smoke "what is a sheaf?"

Requires `ANTHROPIC_API_KEY`. Optionally override the model with `CREW_MODEL`.
Exits non-zero on any failure so it can gate a deploy.
"""
from __future__ import annotations

import logging
import os
import sys

from mathai.math_conversation.crew.crew_builder import build_micro_crew

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    seed = args[0] if args else "Say hello and name one famous math theorem in one sentence."

    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY is not set — the crewai runtime needs it.")
        return 2

    logger.info("seed: %s", seed)
    crew = build_micro_crew(seed)        # lazy-imports crewai
    result = crew.kickoff()
    text = str(getattr(result, "raw", result)).strip()
    logger.info("agent reply (%d chars):\n%s", len(text), text)
    return 0 if text else 1


if __name__ == "__main__":
    raise SystemExit(main())
