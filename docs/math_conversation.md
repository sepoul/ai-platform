# Math conversation — design proposal

A new job type, `math_conversation`, that wraps a small panel of
role-specialized LLM agents in a turn-based "brainstorm" over a
math problem. The conversation reuses every primitive the existing
[`math_qa`](../src/mathai/math_qa/) pipeline depends on (prompt
registry, validation tools, job runner, artifact service) and
produces a single new artifact type that a chat-style UI renders.

This document is a **design proposal**, not a committed roadmap.
The shipping plan and ordering are tracked in
[`NEXT_BEST_STEPS.md`](../NEXT_BEST_STEPS.md).

---

## Goal

Given either (a) a completed `math_qa` job or (b) a fresh question,
run a multi-agent conversation that explores the problem from
distinct perspectives (intuitive/visual, rigorous/symbolic,
synthesizing) and produces a transcript a learner can read like a
study group's whiteboard.

**Non-goal.** Replace `math_qa`. The existing pipeline is the
single-shot answer path; `math_conversation` is a complementary
exploration mode and a sibling `JobDefinition`. Zero modification
to the working answer path.

---

## High-level architecture

A new `JobDefinition` registered via `Domain.register()` alongside
`math_qa`:

```
SeedStep → RunCrewStep → FinalizeStep → End
```

| Node | Responsibility |
|---|---|
| `SeedStep` | Resolve the input. Either hydrate a prior `math_qa` job's artifacts (question + answer + LaTeX + figure) via `hydrate_artifact_refs`, or wrap a fresh `question_text` as a synthetic seed. Output: a `SeededContext` in `MathConversationState`. |
| `RunCrewStep` | Instantiate the agent panel, wire the per-turn callbacks into the existing log stream, run the conversation loop until `max_turns` is reached or any agent invokes the `conclude` tool. Accumulate turns on state. |
| `FinalizeStep` | Assemble the `MathConversationArtifact` from accumulated turns, compute the cost rollup and `stop_reason`, persist via `ArtifactService`. |

Splitting the work this way keeps `RunCrewStep` as the heavy
lifter while `SeedStep` and `FinalizeStep` each get their own log
stages — useful for the live viewer.

### Input shape

```python
class MathConversationInput(BaseInput):
    source_job_id: Optional[UUID] = None
    question_text: Optional[str] = None
    max_turns: int = 12

    @model_validator(mode="after")
    def exactly_one_source(self) -> Self:
        if bool(self.source_job_id) == bool(self.question_text):
            raise ValueError(
                "Provide exactly one of source_job_id or question_text"
            )
        return self
```

`max_turns` is the hard cap. The polite-stop path is a
domain-registered tool, `conclude(reason: str)`, that any agent
may call when the discussion has covered the ground.

### Output shape

One artifact per run:

```python
class ConversationTurn(BaseModel):
    turn_index: int
    agent_role: str
    agent_persona: str
    content: str
    latex: Optional[str] = None
    figure: Optional[FigureSpec] = None
    tool_calls: list[ToolCallRecord] = []
    cost_usd: float

class MathConversationArtifact(BaseModel):
    source_job_id: Optional[UUID] = None
    seed_question: str
    turns: list[ConversationTurn]
    total_cost_usd: float
    stop_reason: Literal["max_turns", "concluded"]
```

Mid-conversation LaTeX and figures live **inline on the turn** —
not as separate rows in the artifact store. The math-ui's existing
`<Latex>` component and figure renderer take values directly, so
the chat renderer reuses them without an indirection.

---

## Personae and skills

Each agent in the panel is composed of a **persona** plus a list of
**skills**. Both live in the [prompt registry](prompt_registry.md);
the registry gains a `kind` discriminator so the existing storage,
versioning, and `/prompts` editing surface apply identically.

### Persona

A Markdown file under
`instructions/math_conversation/personae/<name>.md` with YAML
front-matter:

```markdown
---
kind: persona
role: Algebraist
goal: Drive the conversation toward formal, symbolic clarity.
display_name: "Algebraist"
model: gpt-4o
skills: [symbolic-manipulation, proof-checking]
---

You favor rigor. When a peer makes an intuitive leap, you ask for
the proof. You speak in terms of axioms and lemmas.
```

The body becomes the agent's `backstory`. Front-matter carries
the structured fields: `role`, `goal`, `display_name` (for the UI
chat header), `model` (per-agent model selection), and `skills`
(a list of skill names to load).

### Skill

A Markdown file under
`instructions/math_conversation/skills/<name>.md` with YAML
front-matter declaring a tool allowlist:

```markdown
---
kind: skill
description: "Algebraic manipulation, factoring, simplification."
tool_allowlist: [validate_latex]
---

When manipulating symbolic expressions, prefer step-by-step
simplification. Cite each transformation rule used.
```

The body is appended to the persona's `backstory` at agent
build-time. The `tool_allowlist` constrains which tools the agent
may call.

### Composition

```python
def build_agent(persona_name: str, llm) -> Agent:
    persona = registry.load_persona(persona_name)
    skills = [registry.load_skill(name) for name in persona.skills]
    backstory = persona.body + "\n\n" + "\n\n".join(s.body for s in skills)
    allowed = set().union(*(s.tool_allowlist for s in skills)) | {"conclude"}
    tools = [TOOL_REGISTRY[name] for name in allowed]
    return Agent(
        role=persona.role,
        goal=persona.goal,
        backstory=backstory,
        tools=tools,
        llm=llm,
    )
```

The initial v1 ships **three personae with real prompts** and
**stub skill bodies** — the loading machinery is in place; the
skill content is a follow-up authoring pass.

---

## Live visibility

Each agent action emits a structured event into the existing log
stream so the chat UI can render the conversation as it happens.

```python
class CrewChatEvent(BaseModel):
    event: Literal[
        "signed_in",   # agent joined the conversation
        "is_typing",   # agent is preparing a response
        "message",     # agent emitted a turn
        "tool_call",   # agent invoked a tool
        "tool_result", # tool returned
        "concluded",   # agent called conclude()
        "signed_out",  # crew run finished
        "status",      # budget/cost rollup snapshot
    ]
    agent_role: Optional[str] = None
    display_name: Optional[str] = None
    turn_index: Optional[int] = None
    content: Optional[str] = None
    tool_name: Optional[str] = None
    elapsed_seconds: float
    turns_used: Optional[int] = None
    turns_budget: Optional[int] = None
    cost_usd: Optional[float] = None
```

The events drop through `WorkerLogger`, which the math-ui already
streams over the existing live-logs channel
([`docs/live_logs.md`](live_logs.md)). The chat renderer reads the
event stream as a transcript while the run is in flight, then
swaps to reading the persisted `MathConversationArtifact` once
`FinalizeStep` completes.

---

## Frontend surface

A new domain area in math-ui:

- `math-ui/lib/domains/math-conversation/types.ts` — aliases off
  the generated `schema.d.ts` for `MathConversationArtifact` /
  `ConversationTurn` / `CrewChatEvent`.
- `math-ui/components/conversation/ConversationView.tsx` —
  chat-style renderer (bubble per turn, persona avatar +
  `display_name`, inline LaTeX via the existing `<Latex>`, inline
  figures via the existing figure renderer).
- Entry points:
  - A "Run conversation on this answer" CTA on completed `math_qa`
    job detail pages (submits with `source_job_id`).
  - A submit-from-scratch entry on the submit page for
    `math_conversation` (submits with `question_text`).

The conversation page reuses `components/library/` primitives
(`PageContainer`, `Section`, `Markdown`, `Latex`). The chat-bubble
pattern is the only genuinely new component and lives under
`components/library/` so a future use can pick it up.

---

## Layering

For v1 the implementation lives entirely under
`src/mathai/math_conversation/` — a sibling domain to
`mathai.math_qa`. Cross-cutting helpers (the
agent-build machinery, the callback bridge) are flagged as
candidates for extraction to `ai_platform.ai.crew.*` once a second
domain wants this style of multi-agent work. Until then,
domain-local keeps the platform layer focused on what's actually
shared.

This is consistent with [`AGENTS.md`](../AGENTS.md): generic
platform primitives live in `ai_platform.*`, domain logic in
`mathai.*`.

---

## Dependency strategy

CrewAI is the multi-agent runtime. **Both runtimes use Anthropic** —
`math_qa` via `pydantic_ai`, the conversation panel via CrewAI's native
Anthropic provider — because per-image isolation lets each runtime carry
the anthropic SDK its stack is happy with.

- **No LiteLLM.** CrewAI 1.14.5's `litellm` is an *optional* extra,
  imported lazily; the `LLM` factory routes native providers (`openai`,
  `anthropic`, `azure`, `bedrock`, …) to their SDKs and only falls back
  to LiteLLM for non-native ones. We never touch the fallback.
- **Slim runtimes.** The worker base ships only `pydantic-graph` (the
  platform graph framework that both runtimes need). Each runtime's LLM
  stack lives in its own extra:
  - `packages/worker[default]` → `pydantic-ai-slim[anthropic,duckduckgo,logfire]`
    (math_qa). Brings anthropic ~0.105.
  - `packages/worker[crewai]` → `crewai[anthropic]` (math_conversation).
    Brings anthropic ~0.73 — older, but `client.messages.create` passes
    the model id through to the API, so newer Claude model ids work fine.
  Crew agents get `crewai.LLM(model="anthropic/claude-…")`. Requires
  `ANTHROPIC_API_KEY` in the worker env. Per-image isolation removes the
  historical `crewai[anthropic]` vs `pydantic-ai-slim` SDK clash — they
  never share an interpreter.

### The unavoidable clash: CrewAI vs. Logfire over OpenTelemetry

Per-image isolation resolves the *anthropic* SDK clash, but a second
constraint no provider choice avoids: **CrewAI 1.14.5 pins
`opentelemetry-sdk <1.35`, while Logfire** (pulled by
`pydantic-ai-slim[logfire]`) **needs `>=1.39`.** No CrewAI release
loosens it. The two **cannot coexist in one Python interpreter**, so
the crewai image installs `packages/worker[crewai]` only (which does
not pull `pydantic-ai-slim` at all) and exports traces to Logfire via
OTLP instead.

Resolution: **per-runtime worker pools** (see
[`ai_platform/jobs/runtimes.py`](../src/ai_platform/jobs/runtimes.py)).
A *runtime* is an isolated dependency environment. Runtime is scoped at
the **domain** level: the import manifest in
[`composition_root.py`](../src/ai_platform/composition_root.py)
(`runtime → domain modules`) is the single source of truth. There is no
per-job runtime field — you can't read one without importing the module
that may crash on a slim env. A worker serves one runtime
(`WORKER_RUNTIME`), imports only that runtime's domains, and so claims
only its own jobs.

| Runtime | Install | Stack | Job types |
|---|---|---|---|
| `default` | `packages/worker[default]` | pydantic_graph + pydantic_ai + Anthropic + **Logfire** (otel ≥1.39) | `math_qa`, API process |
| `crewai`  | `packages/worker[crewai]`  | pydantic_graph + **CrewAI[anthropic]** (otel <1.35), no pydantic_ai, no Logfire SDK | `math_conversation` |

The manifest assigns `mathai.math_conversation.domain` to `crewai`, so a
`default` worker never imports it (leaving those jobs `PENDING`) and the
`crewai` worker pool picks them up. The two stacks never share an
interpreter. A domain that needs to span runtimes is split into one
domain per runtime.

**The load-bearing rule** that makes this work: building a
`JobDefinition` must be importable from *any* runtime. The composition
root imports domains lazily, per runtime, so the `crewai` worker never
imports `math_qa` (→ `basic_agent` → `pydantic_ai` → `logfire`), and the
`default` worker never imports `math_conversation`'s lazy crewai bodies.
Heavy crew imports (`crewai`) live **inside `RunCrewStep`** (and
`crew/` builders), not at module load, so the API and `default` worker
register the conversation job without `crewai` installed. (The API
importing *all* domains is what forces this rule; it only needs each
job's schemas, not its execution code, so decoupling the API from
runtime is flagged as future cleanup.)

**Observability per runtime.** The `default` runtime runs the Logfire SDK
directly. The `crewai` runtime can't (otel pin) but ships
`opentelemetry-exporter-otlp` — Logfire is an OTLP collector, so crew traces
can land in the same project via direct OTLP export. v1 surfaces crew
progress through the structured `CrewChatEvent` log stream (below) and wires
OTLP-to-Logfire as a follow-up.

**Day-0 burn-in:** `uv pip install -e "packages/worker[crewai]"` resolves
(verified: otel-sdk 1.34.1, anthropic 0.73, crewai 1.14.6, pydantic-graph
1.104; no pydantic-ai-slim, no logfire); `pytest tests/` stays green; a
trivial native Anthropic CrewAI agent completes one call via the smoke
entrypoint `python -m ai_platform.entrypoints.crewai_smoke "<question>"`.

CrewAI memory features (long-term, entity, contextual) are **off**
for v1 (`Crew(memory=False)`). Each conversation is hermetic. This
also keeps the embedding-store dependency tree out of the picture.

---

## Persistence and recovery

The `MathConversationArtifact` is persisted once, at end-of-run, by
`FinalizeStep`. The existing `PersistencePolicy` contract is
unchanged.

Live visibility during a run comes from the structured event
stream alone. If the user refreshes mid-run, the chat renderer
reconstructs the in-progress conversation from the appended event
log; once the run completes, it switches to the persisted artifact
as the source of truth.

Incremental per-turn persistence is intentionally out of scope for
v1 — it would require a new "streaming artifact" semantic on
`PersistencePolicy` that does not exist today. A future iteration
may add it; not blocking.

---

## Cost and termination

Two stop conditions:

1. **`max_turns`** (job-input parameter; default 12, ceiling 30) —
   hard fallback. The agent loop short-circuits when reached.
2. **`conclude(reason: str)`** — a domain-registered tool any agent
   may call when the conversation has reached a natural close.

Token usage per agent is accumulated and reported as
`total_cost_usd` on the artifact, plus per-turn `cost_usd`
deltas, plus periodic `status` events in the log stream. Cost is
**observed and surfaced**, not enforced — a single overrun
completes; runaway cost is gated by `max_turns` alone.

---

## What ships in v1 ✅

Everything in this list landed on `feat/conversation-panel`:

- `math_conversation` `JobDefinition` + the 3-node graph above
  (Seed → RunCrew → Finalize).
- `MathConversationArtifact`, `ConversationTurn`, `CrewChatEvent`.
- Persona/skill loaders extending the prompt registry with a
  `kind` discriminator.
- Three personae with real prompts (skill bodies are stubs — see
  v1.x follow-ups below).
- Native CrewAI Anthropic LLM wiring; the multi-persona panel +
  round-robin turn loop + `conclude` tool that lets any panelist
  end the discussion early.
- `SeedStep` artifact hydration: a `source_job_id` from a completed
  `math_qa` job projects question + answer + latex + figure into the
  panel's seed context, so the panel refines a single-shot answer
  rather than starting from scratch.
- math-ui chat renderer + submit + a "Run conversation on this
  answer" CTA on completed math_qa job pages.
- Slim per-image runtime: `packages/worker[crewai]` drops
  `pydantic-ai-slim` entirely and brings `crewai[anthropic]` instead;
  `packages/worker[default]` is unchanged. See §Dependency strategy.
- `CrewChatEvent` exposed in OpenAPI for typed FE codegen (via a
  small schema-export endpoint on the math_conversation domain).

## Post-v1 follow-ups

Tracked in detail in
[`NEXT_BEST_STEPS.md`](../NEXT_BEST_STEPS.md) — backend §8 and
Frontend §9. Short list:

- **§8a** Fill in the five skill bodies (stubs today).
- **§8b** Smoke-test crewai's anthropic 0.73 with Claude Sonnet 4.5
  inside the built image on first deploy. Host-side smoke already
  passed (`.venv-crewai` mirrors the image's deps); the in-image
  check remains.
- **§8c** OTLP → Logfire export for crew traces (currently observable
  only via the SSE `CrewChatEvent` stream).
- **§8d** Per-runtime Celery routing (today's single Celery pool runs
  only the default runtime).
- **§8e** ✅ `ArtifactService.list_by_job` — SeedStep hydration is now
  one Supabase query (shipped alongside Perf §9 batched listing).
- **§8g** Per-turn cost surfacing — crewai+anthropic doesn't populate
  `result.token_usage.total_cost`, so `cost_usd` always reads `$0`;
  compute from `input_tokens`/`output_tokens` × a Claude price table.
- **§8f** v2 deferrals (no current ticket): manager-led panel,
  cross-conversation memory, per-turn persistence, mid-run HITL.
- **Frontend §9** Chat-bubble library promotion, `ConversationTurn.figure`
  rendering when a skill produces one, optional workflow stepper on
  the conversation page, tool_call/tool_result event rendering.

What does **not** ship in v1 (architectural choices, not deferrals):

- A manager-agent / hierarchical CrewAI process — sequential
  turn-order is the v1 choice; manager-led delegation is a later
  iteration once the artifact contract has soak time.
- Cross-conversation memory — each conversation is hermetic
  (`Crew(memory=False)`).
- Incremental per-turn persistence — the artifact is minted once at
  end-of-run; mid-run state lives only in the event stream.
- Mid-run human-in-the-loop — the job has no review gate
  (`JobControl.gates=[]`).
