"""Provider helpers — agent factories and media interpreters.

Thin, optional factories a domain calls from its `[execution]` workflow. Import
each from its submodule (same convention as `basic_agent` today — no re-export
magic, since a factory and its module share a name):

    from ai_platform.ai.providers.basic_agent import basic_agent      # Anthropic
    from ai_platform.ai.providers.openai_agent import openai_agent    # OpenAI sibling
    from ai_platform.ai.providers.audio import (
        transcribe_audio,    # bytes / path / file-like -> text
        AudioInterpreter,    # media-first-class: storage_ref -> text
    )

Where the deps live:

- `openai` SDK — in the **worker base**, so it's present in *both* runtimes
  (it has no otel-sdk dep, so it's safe across the pool split). The audio
  helpers therefore work under either framework.
- `pydantic_ai` — the **`default`** runtime's framework (so `openai_agent`,
  like `basic_agent`, is a `default`-runtime helper).
- `crewai` — the **`crewai`** runtime's framework.

Each submodule defers its framework import into its function bodies, so
importing this package (or the modules) never drags a framework into a base or
control-plane process.
"""
