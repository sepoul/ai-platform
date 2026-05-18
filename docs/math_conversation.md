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
model: claude-opus-4-7
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
`mathai.math_qa`. Cross-cutting helpers (the LLM adapter, the
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

The CrewAI framework is the proposed multi-agent runtime. CrewAI's
default LLM transport is LiteLLM, which adds non-trivial
dependency surface. Two paths are tracked:

1. **Plan A — custom LLM adapter.** CrewAI accepts a `BaseLLM`
   subclass via the `llm=` parameter on `Agent`. A small adapter
   in `mathai.math_conversation.llm` delegates to the existing
   Anthropic-backed `basic_agent` in
   [`ai_platform.ai.providers`](../src/ai_platform/ai/providers/),
   bypassing LiteLLM at runtime. Worker image only — the API
   process does not import this module.

2. **Plan B — LiteLLM as the router.** If the bridging adapter
   proves impractical, fall back to LiteLLM under the hood,
   restricted to the worker image. The API image stays slim
   because it never imports the conversation domain.

A **Day-0 burn-in pre-task** (see
[`NEXT_BEST_STEPS.md`](../NEXT_BEST_STEPS.md)) validates the
LiteLLM dependency in isolation, behind an `LLM_ROUTER` env-var
gate, *before* any CrewAI integration begins. This converts an
in-flight risk into a measurable up-front step.

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

## What ships in v1

- New `math_conversation` `JobDefinition` and the 3-node graph
  above.
- `MathConversationArtifact`, `ConversationTurn`, `CrewChatEvent`.
- Persona/skill loaders extending the prompt registry with a
  `kind` discriminator.
- Three personae with real prompts; skill bodies as stubs.
- LLM adapter (Plan A) and `conclude` tool.
- math-ui chat renderer + submit/CTA entry points.
- Day-0 LiteLLM burn-in pre-task completed and measured.

What does **not** ship in v1:

- Filled-in skill bodies (deferred to a follow-up authoring pass).
- A manager-agent / hierarchical CrewAI process (sequential
  turn-order in v1; manager-led delegation is a later iteration
  once the artifact contract has soak time).
- Cross-conversation memory.
- Incremental per-turn persistence.
- Mid-run human-in-the-loop (`human_input=True` on tasks).

The ordering, milestones, and acceptance criteria are tracked in
[`NEXT_BEST_STEPS.md`](../NEXT_BEST_STEPS.md).
