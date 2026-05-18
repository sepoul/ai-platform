# Features

Ideas to build out. Not committed designs — capturing direction so it
doesn't get lost.

---

## Iterative figure refinement

The first slice of figure generation
([NEXT_BEST_STEPS §1o](NEXT_BEST_STEPS.md)) gives one LLM call → one
figure spec, validated structurally by `validate_figure`. The agent
imagines the layout from scratch each time using the freeform DSL
(blobs, rects, arrows, labels at normalized coords). This works for
simple cases but fails predictably on:

- **Layout collisions** — overlapping shapes, labels stamped on top
  of each other, arrows that cross at glyph centers.
- **Mathematical correctness** — arrow direction wrong (e.g. Klein
  bottle edge identification flipped), missing pieces (chart shown
  but its target patch omitted), labels swapped.
- **Aesthetic quality** — cramped spacing, asymmetry where symmetry
  was meaningful, no margin.

`validate_figure` only catches "is this JSON-shaped right" — not
"does it actually communicate the math". The next iteration is an
auto-critique loop, with optional human-in-the-loop for high-stakes
figures.

### Architecture

A self-contained subgraph that runs after `RenderFigureStep`:

```
RenderFigureStep
       ↓
FigureCritiqueStep ←──────────┐
       ↓                      │
   accept? ─yes→ End          │ revise (with critique)
       │ no                   │
       ↓                      │
FigureReviseStep ─────────────┘
```

Capped at `max_iterations` (start with 3) so a stuck agent doesn't
spin forever. On exhaustion, accept whatever we have and log
`convergence_failed=true` on the artifact so we can spot patterns.

### `FigureCritiqueStep` — LLM-as-judge

Reads the question + answer + the rendered spec (serialized as
JSON — coordinates and types are enough for an LLM to infer
overlap, proximity, missing pieces). Output:

```python
class FigureCritique(BaseModel):
    accept: bool
    issues: list[str]      # specific problems, e.g. "label at (0.4,0.5) overlaps blob U"
    suggestions: list[str] # how to fix, e.g. "move the label to (0.4, 0.42)"
```

Use a different model than the original generator (Sonnet for
critique, Haiku for first-pass generation), or the same model with
an explicit "critic" persona — research suggests LLM-as-judge works
best with role-distinct prompting.

### `FigureReviseStep`

Re-runs the figure agent with `previous_spec` + `critique` in the
user prompt. Same `validate_figure` tool loop for structural checks.
Increments `state.figure_revisions`.

### Human-in-the-loop variant

For lecture-grade figures, wrap the subgraph in a `NodeGate`:

- After `FigureCritiqueStep` accepts (or `max_iterations` exhausts),
  pause for human review with the figure rendered.
- User can:
  1. **Accept** — proceed to `GenerateLatexStep` and the existing
     answer-level review gate.
  2. **Reject with comment** — comment becomes the user-prompt
     input for another `FigureReviseStep`, looping back through
     critique. The runner re-paths via the gate's review schema.

Reuses the existing `UserComment` schema with a
`reject_for_revision: bool` flag — when set, the runner routes back
to revision instead of advancing.

### What to build first

1. **`FigureCritiqueStep` with LLM-as-judge.** No human gate yet.
   This alone catches obvious layout issues. Every critique logs
   through the worker logger so the user watches the agent
   self-correct.
2. **`FigureReviseStep`** wiring the loop. Iteration cap on state.
3. **UI breadcrumbs in the logs panel** — surface each candidate
   spec (id-only; the user can click through to render in the
   scratchpad if they want to see what was tried).
4. **Human-in-the-loop gate** last. Once auto-loop is good enough,
   the manual override is a small addition.

### Open questions

- **Vision feedback.** The critic reads JSON, not pixels. For real
  visual judgment we'd need a vision-model rendering the SVG and
  evaluating it. Out of scope for v1; the natural escalation if
  JSON-only critique plateaus.
- **Cost.** Each iteration is 2 LLM calls (revise + critique). Cap
  at 3 means up to ~7 calls total per figure (1 generate + 3 ×
  (revise + critique)). Worth it for figures the user will
  actually look at.
- **Per-figure storage.** Should we keep the rejected drafts as
  separate artifacts (history) or just the final spec (clean)?
  Probably final-only on the result; iteration history can live
  in `JobRecord.events` if we want it for debugging.
- **Critic blindness.** A critic that's too lenient is useless; one
  that's too strict won't converge. Calibrate by running the
  critique step against known-good and known-bad specs from the
  scratchpad as a regression set.

### Reusable beyond figures

The same shape (generate → critique → revise → human gate) is
exactly what
[the reusable figure stack's `FigureRefinementGate`](#reusable-figure-stack)
sketches for visual artifacts in general. It also fits LaTeX correctness
escalation — when the structural validator passes but the typeset
output is mathematically wrong, a critique loop catches it. This is
the generic "iterative artifact refinement" pattern; the figure
case is just where we cut our teeth.

---

## MathBox visual-math agent

Agentic workflow that produces visual math (topology to start with)
renderable in the browser via [MathBox](https://gitgud.io/unconed/mathbox).

### Why MathBox

It runs in the existing Next.js UI. By making MathBox JSON the agent's
output type, the contract between backend and frontend stays declarative
— the agent is just emitting a render spec, the frontend is just a
renderer.

### Flow

1. **Agent runs** in this repo's job/graph machinery and produces a
   generic MathBox JSON payload as its artifact.
2. **Artifact saved** to the workspace, referenced from the job result
   (the artifacts-as-first-class-outputs path that already exists).
3. **Worker → API hand-off**: worker finishes the job, FastAPI knows
   the result is ready. Either FastAPI pushes a notification to
   Next.js, or Next.js polls — TBD, both are cheap.
4. **Next.js validates**: pulls the JSON and tries to compile it
   against MathBox. Compilation is the validation step — if it
   compiles, it's renderable.
5. **Render**: if compile succeeds, render in the UI.
6. **Human review**:
   - Accept → result is final, job closes out clean.
   - Reject with a prompt → that prompt feeds back into a new agent
     iteration. Loop until accepted or capped.

### Open questions / things to figure out later

- Notification vs. polling between API and Next.js. WebSocket / SSE
  vs. dumb polling — depends on how live the UI needs to feel.
- Compile-failure handling: the user sees nothing on failure. The
  repair loop runs automatically between Next.js and FastAPI/worker —
  Next.js reports the compile error back, the agent re-attempts, repeat
  up to N times. Only after N failures does anything surface to the
  user (likely as a hard error, not a broken render).
- Reuse of the existing review gate (`NodeGate` + `set_review`) — the
  reject-with-prompt loop maps cleanly onto it.

### Decided

- **MathBox JSON stays a generic dict server-side** — no Pydantic
  schema mirror. Compile validation lives in Next.js where the real
  MathBox types are, so server-side strong typing would just duplicate
  truth and drift.

---

## Reusable figure stack

Once the topology agent works end-to-end, the same pieces should plug
into other math-learning workflows where figures aid understanding —
Math Q&A, step-by-step explainers, lessons, etc. Sketching the agentic
architecture so it's clear what to reuse vs. rebuild.

### Reusable platform pieces

- **`MathBoxFigureArtifact`** — single artifact type, registered once
  in the math-learning artifact registry. Every domain that produces a
  figure mints one. UUIDs make them shareable across jobs (one figure
  can be referenced by an answer, a lesson, and a quiz).
- **`RenderFigureNode`** — a graph node any domain can drop into its
  pydantic_graph. Input: a small spec (concept + hints) on state.
  Output: a `MathBoxFigureArtifact` ID written back to state. Closes
  over the same MathBox-agent stack as the standalone topology
  workflow.
- **`FigureCompileGate`** — generic `NodeGate` whose review type is
  the Next.js compile result (success or structured error). The same
  automatic repair loop (N retries → surface) lives behind it. Domains
  opt in by listing the gate in their `ExecutionPolicy`.
- **`FigureRefinementGate`** — separate `NodeGate` whose review is the
  user's accept / reject-with-prompt. Distinct from compile so the two
  loops can be tuned independently.

### Plugging it into Math Q&A

Drop-in pattern: `GenerateAnswerStep → MaybeRenderFigureStep → End`.

- `MaybeRenderFigureNode` inspects the answer (and a "needs visual?"
  hint the answer model emits) and either:
  - early-Ends with no figure, or
  - kicks off the figure sub-graph (`RenderFigureNode` + the two
    gates above) and merges the resulting `MathBoxFigureArtifact` ID
    into `state.artifact_refs`.
- `MathQAResult` grows an optional `figure: MathBoxFigureArtifact`
  field, hydrated from refs the same way `question` / `ai_response` /
  `review` already are.

No new infra — same artifact-refs mechanism, same gate machinery.

### Other use cases the same pieces unlock

- **Step-by-step explainer** — graph emits a sequence of
  `MathBoxFigureArtifact`s, one per step. The result references all
  of them in order; UI scrubs through.
- **Concept lessons** — a higher-level graph orchestrates several
  sub-figures + prose between them. Each sub-figure is its own job or
  sub-graph, all minting into the same artifact store.
- **Quiz / drill** — figure + question + expected answer, where the
  figure is the prompt. Reuses `MathBoxFigureArtifact` as the carrier
  for the question itself.
- **Few-shot bank** — accepted figures (passed user review) become a
  growing dataset of (concept → MathBox JSON) examples. Future
  generations seed the agent with these. Pure side-effect of the
  artifact store; no new code path.

### Things that need thinking later

- Where the figure sub-graph lives — own domain (`viz_math`), or a
  shared library every domain composes in. Probably the latter, since
  the agent is generic enough.
- Caching: identical figure specs should reuse the same artifact ID
  rather than re-minting. Likely keyed on a hash of the spec.
- Streaming partial figures back to the UI for long renders.

---

## Math Q&A artifact stabilization

Today Math Q&A mints a thin answer (`GeneratedAnswerArtifact` plus a
`UserCommentArtifact` for review). For the platform to be a *learning*
tool — not a Q&A tool — the result needs to be a small knowledge
package: the question, the answer, and the surrounding learning
context. Approach: reverse-engineer the artifacts first; the workflow
falls out of them.

### User stories

A learner asking "what's an eigenvalue?" should get back:

1. **LaTeX-displayable content** — "I want formulas typeset, not
   pasted as plain text, so I can read them naturally."
2. **References to books / papers** — "I want pointers to where I can
   read more, so I can verify and go deeper."
3. **Exercises and short questions** — "I want practice problems
   matched to the concept, so I can check my understanding."
4. **Real-world / physics applications** — "I want to see why the
   concept matters outside math, so motivation isn't lost."
5. **Prerequisites** — "If I'm stuck, I want to know what to learn
   first, ranked by closeness to the concept."
6. **Mathematical next steps** — "I want to know where this concept
   leads if I keep going."
7. **Local knowledge graph** — "I want to see the concept's
   neighborhood — what's adjacent, what generalizes it, what
   specializes it — so I can navigate."

### Target artifacts (reverse engineered)

`ConceptArtifact` is the **unit of reuse**. Refs, prereqs, exercises,
applications all attach to a concept and survive across questions —
they're not per-answer one-shots.

- **`ConceptArtifact`** — `name` (canonical slug, e.g. `"eigenvalue"`),
  `aliases: [str]`, `description: RichContent`,
  `formal_definition: RichContent | None`. Unique by `name` in the
  workspace.
- **`RichContentArtifact`** — interleaved segments
  `[{kind: "text" | "inline_latex" | "block_latex", value: str}]`. The
  format every text-bearing artifact uses when it might contain math.
  Drops the "is this LaTeX or plain text?" question on the UI side.
- **`ReferenceArtifact`** — `title`, `authors`, `year`,
  `kind: "book" | "paper" | "lecture_notes" | "url"`, `locator`
  (chapter/section/DOI/URL), `notes: RichContent | None`. Reusable —
  one reference attaches to many concepts.
- **`ExerciseArtifact`** — `prompt: RichContent`,
  `difficulty: "warmup" | "drill" | "challenge"`,
  `expected_answer: RichContent`, `hints: [RichContent]`,
  `concept_refs: [UUID]`.
- **`ApplicationArtifact`** —
  `domain: "physics" | "engineering" | "biology" | "finance" | "other"`,
  `summary: RichContent`, `concept_refs: [UUID]`.
- **`ConceptRelationArtifact`** — typed directed edge:
  `source_concept`, `target_concept`,
  `kind: "prerequisite_of" | "leads_to" | "specializes" | "generalizes" | "related_to"`,
  `weight: float | None`. The knowledge graph **is** the union of these
  edges; no separate "graph" artifact needed.
- **`MathAnswerArtifact`** (replacing `GeneratedAnswerArtifact`) —
  `body: RichContent`, `reasoning_steps: [RichContent]`,
  `concept_refs: [UUID]`, `confidence: float`. LaTeX-aware end-to-end.

`MathQAResult` becomes a hub that hydrates by ref:

```python
class MathQAResult(BaseJobResult):
    job_type: Literal["math_qa"]
    question:      MathQuestionArtifact | None
    answer:        MathAnswerArtifact | None
    review:        UserCommentArtifact | None
    concepts:      list[ConceptArtifact]
    references:    list[ReferenceArtifact]
    exercises:     list[ExerciseArtifact]
    applications:  list[ApplicationArtifact]
    prerequisites: list[ConceptArtifact]
    next_steps:    list[ConceptArtifact]
    neighborhood:  list[ConceptRelationArtifact]
    artifact_refs: list[UUID]
```

### Workflow sketch

```
ParseQuestionStep
  ↓
IdentifyConceptsStep        — NL question → existing ConceptArtifacts
                              (by name/alias); mint new ones if none match
  ↓
GenerateAnswerStep          — prompts LLM with concepts in scope;
                              emits RichContent answer
  ↓ (fan-out per concept)
GatherReferencesStep        — existing refs first; LLM-suggest more if sparse
GenerateExercisesStep       — warmup → drill → challenge ladder
GatherApplicationsStep      — cached lookup + LLM fill-in
ResolvePrerequisitesStep    — walks ConceptRelation graph (prerequisite_of)
ResolveNextStepsStep        — walks ConceptRelation graph (leads_to)
BuildNeighborhoodStep       — N-hop slice of ConceptRelation graph
  ↓
AssembleResultStep
  ↓
End
```

Platform pieces it leans on, no new infra:

- **Artifact-first persistence** — every step mints typed artifacts;
  the result hydrates by ref. Same path `question` / `ai_response` /
  `review` use today.
- **`PersistencePolicy.on_complete`** — already idempotent. New logic
  just expands the set of types it knows to look for.
- **Cache by concept** — gather/resolve steps short-circuit when a
  concept already has known refs/applications/relations. The artifact
  store is the cache.

### Things to figure out

- **Concept identification quality.** "What's an eigenvalue?" →
  `ConceptArtifact("eigenvalue")` is the bottleneck. Probably bootstrap
  with a curated seed set + LLM matching against names/aliases, with a
  human review gate when the model isn't confident.
- **Knowledge-graph seeding.** A cold workspace has no
  `ConceptRelationArtifact`s. Options: import from a curated source
  (Wikipedia category graph, MathSciNet, OEIS), or accept early
  answers as sparse and grow the graph job-by-job. Probably both.
- **LaTeX correctness.** ✅ Initial slice landed: a
  `LatexAnswerArtifact` is now produced by `GenerateLatexStep` after
  the AI text answer, using a `validate_latex` agent tool that
  round-trips to `math-ui` `POST /api/tools/validate-latex` (KaTeX
  with `throwOnError: true`). The agent emits markdown-with-LaTeX-
  delimiters; the validation route's `mode="document"` splits on
  `\(...\)` / `\[...\]` and validates each math segment, returning
  the first failing segment with `segment` + `segment_index` so the
  agent can self-correct. The agent loops on tool feedback inside
  the node — no graph-level gate yet. Promoting this to a
  `LatexCompileGate` (analogous to the future `FigureCompileGate`)
  comes when `RichContentArtifact` lands and other content kinds need
  the same loop.
- **Concept naming canon.** `"eigenvalue"` vs `"eigenvalues"` vs
  `"Eigenvalue"`. Slugify on creation, store alternates as `aliases`.
- **Exercise grading.** Comparing a learner-typed answer against
  `expected_answer` (which itself contains math) needs a separate
  comparison step. Defer until exercises are surfaced in the UI.

### Doesn't fit yet (parking)

- Rendered figures via MathBox — `MathAnswerArtifact` can carry a
  `figure_ref: UUID` field once the reusable figure stack is real.
- Per-user mastery / progress tracking — separate read-side, not a
  Math Q&A artifact.

---

## Math conversation (multi-agent brainstorm)

A sibling `JobDefinition` to `math_qa` that runs a small panel of
role-specialized agents — intuitive/visual, rigorous/symbolic,
synthesizing — over either a completed `math_qa` job or a fresh
question. Produces a chat-style transcript artifact that a learner
can read like a study group's whiteboard.

Full design proposal:
[`docs/math_conversation.md`](docs/math_conversation.md).
