# math_conversation — build checkpoint

Resume point for the `math_conversation` feature on branch
`feat/math-conversation`. Pairs with the design
([`math_conversation.md`](math_conversation.md)) and the ticket
breakdown (`local/crew-ai-implementation-plan.md`, gitignored).

_Last updated 2026-05-21._

## Status at a glance

| Ticket | What | State |
|---|---|---|
| T1 | Domain skeleton (models, state, graph, JobDefinition, registration) | ✅ done |
| T2 | Artifact schema (`MathConversationArtifact` + inline-turn shape) | ✅ done |
| T3 | Persona/skill registry (`kind`, loaders, 3 personae + 5 skills) | ✅ done |
| T4 | `CrewChatEvent` + emitters on the log stream | ✅ done |
| T7 | API entry points (generic union routes it; integration-tested) | ✅ done |
| — | **Per-runtime worker pools** (CrewAI⇄Logfire otel isolation) | ✅ done |
| T5 | CrewAI wiring (`build_agent`/`build_crew`/`step_callback`/`conclude`) | ⏳ blocked on crewai install |
| T6 | Step bodies (SeedStep hydration, RunCrewStep loop, FinalizeStep) | ⏳ needs T5 |
| T-UI | math-ui chat renderer + submit/CTA + `gen:api` | ⏳ open (frontend) |
| T8 | Cost surfacing | ⏳ needs T6 |
| T9 | Docs / AGENTS.md row | ⏳ after v1 lands |

Full backend test suite: **91 green** (CrewAI-free; no network needed).

## Branch commits (ahead of `main`)

```
e1d1278 feat(runtimes): per-runtime worker pools to isolate conflicting deps
ca43a33 build(math_conversation): add crewai dependency (OpenAI provider)
bd3dfbb test(math_conversation): submission integration coverage (T7)
d632828 feat(math_conversation): persona/skill registry extension (T3)
4105e3e feat(math_conversation): domain skeleton + artifact schema + chat events
```

## Decisions locked in (don't relitigate)

- **Crew runs on Anthropic** (CrewAI's native Anthropic provider). The
  original OpenAI choice dodged a `crewai[anthropic]~=0.73` vs
  `pydantic-ai-slim>=0.97` clash in *one* interpreter; the Phase-3b
  physical package split puts the two runtimes in separate images, so
  each carries the anthropic version its stack is happy with. Plain
  `crewai` (no `[anthropic]` extra) doesn't constrain it; the SDK is
  available transitively via `pydantic-ai-slim[anthropic]`.
- **No LiteLLM.** It's an optional crewai fallback for non-native
  providers only; we never touch it. (A throwaway in-process litellm
  burn-in was reverted — it bypassed pydantic_ai and went dark in Logfire.)
- **CrewAI ⇄ Logfire can't coexist in one interpreter** (otel-sdk
  `<1.35` vs `>=1.39`). Resolved with **per-runtime worker pools**, not
  by dropping either. See [`ai_platform/jobs/runtimes.py`](../src/ai_platform/jobs/runtimes.py).

## The runtime model (how isolation works)

Runtime is scoped at the **domain** level. The single source of truth is
the import manifest in [`composition_root.py`](../src/mathapp/composition_root.py)
(`runtime → domain modules`); there is no per-job runtime field, because
you can't read one without importing the module that may crash on a slim
env. That one map does double duty:

- **Import isolation.** A worker imports only its runtime's domains, so a
  slim env (no other runtime's deps) still boots — the `crewai` worker
  never imports `math_qa` → `basic_agent` → `logfire`.
- **Job routing.** Having imported only its own domains, the worker's
  registered job set already contains *only* its jobs; it claims those
  (`claim_next_pending(job_types=...)`). Other runtimes' jobs stay
  `PENDING` for their pool. (No `select_for_runtime` — it was redundant
  and is gone.)

A domain spanning runtimes is split into one domain per runtime. Runtime
owns the dep stack; a domain just declares JobDefinitions.

- **Load-bearing rule:** building a `JobDefinition` must stay importable
  from any runtime. Heavy crew imports (`crewai`) go **inside
  `RunCrewStep`**, never at module top — otherwise the API and `default`
  worker (no crewai installed) can't register the conversation job.
- **Flagged for later (`api-runtime-decoupling`):** the API importing
  *all* domains is the only thing forcing that load-bearing rule. The API
  only needs each job's schemas, not its execution code, so it shouldn't
  have to care about runtime at all. Future cleanup; see the TODO in
  `composition_root.py`.

| Runtime | Install | Stack | Jobs |
|---|---|---|---|
| `default` | `packages/worker[logfire]` | pydantic_ai + Anthropic + Logfire (otel ≥1.39) | `math_qa`, API |
| `crewai` | `packages/worker[crewai]` | CrewAI + Anthropic (otel <1.35), no Logfire SDK | `math_conversation` |

## How to resume (T5/T6)

1. **Provision the crewai runtime** (its own image/venv):
   `uv pip install -e "packages/worker[crewai]"`. Set `ANTHROPIC_API_KEY`.
   (Compose: `docker compose --profile crewai up worker-crewai`.)
2. **T5 — crew engine** (all imports lazy inside the node / `crew/` modules):
   - `crew/personae.py` — `build_agent(persona_name, llm) -> crewai.Agent`
     from `mathai.math_conversation.registry.load_persona/load_skill`.
   - `crew/skills.py` — skill loader + tool-allowlist enforcement.
   - `crew/crew.py` — `build_crew(personae, llm_factory, step_callback) -> Crew`,
     sequential `Process`, `Crew(memory=False)`,
     `crewai.LLM(model="anthropic/claude-…")` (anthropic SDK present via
     `pydantic-ai-slim[anthropic]`).
   - `tools/conclude.py` — `conclude(reason)` tool flips `state.concluded`.
   - Wire CrewAI `step_callback` → the existing
     [`CrewChatEmitter`](../src/mathai/math_conversation/crew/callbacks.py).
3. **T6 — fill the node bodies** in
   [`workflow.py`](../src/mathai/math_conversation/workflow.py): SeedStep
   hydration from a source `math_qa` job (guard: source must be
   `completed`), RunCrewStep turn loop (cap `max_turns`, respect
   `conclude`), FinalizeStep already persists the artifact.
4. **Acceptance probes** (the Day-0 burn-in): `packages/worker[crewai]`
   resolves (✓ verified, otel-sdk 1.34.1); a trivial native-Anthropic
   crewai agent completes one call; an end-to-end `math_conversation`
   job run by the `crewai` worker produces a `MathConversationArtifact`.

## Open follow-ups

- **Crew-call tracing in Logfire.** The crewai runtime can't run the
  logfire SDK (otel pin), but it *does* pull `opentelemetry-exporter-otlp`,
  and Logfire is an OTLP collector — so crew traces can land in the same
  project via **direct OTLP export**. Wire this for true end-to-end
  observability.
- **T-UI** — regenerate `math-ui` `schema.d.ts` (`npm run gen:api`) to
  pull `MathConversationInput` / `MathConversationArtifact`, then build
  the chat renderer + live `CrewChatEvent` parser + the "Run conversation
  on this answer" CTA.
- **Per-runtime Celery routing** — the single Celery pool still registers
  all domains; a queue + pool per runtime is future work.
- **Skill bodies** — currently stubs; an authoring pass fills heuristics
  + few-shots.
