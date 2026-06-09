# Platform requirements

What the [math-app](../README.md) domain needs from the
[ai-platform](https://github.com/sepoul/ai-platform) to enable the
directions in [`FEATURES.md`](../FEATURES.md). This is a **domain →
platform** ask list: each item is scoped to keep the platform thin
(the design contract's `out of scope` §13 still holds — embeddings,
RAG, ASR, vision, model routing all stay domain-side). Port these into
the platform's `NEXT_BEST_STEPS.md` as backlog entries.

The lens: the platform owns *the catalog and the orchestration*; the
domain owns *the compute and the data*. Every requirement below is the
smallest platform primitive that lets the domain own the rest.

---

## Feature → requirement matrix

| FEATURES.md feature | PR-1 media | PR-2 shared types | PR-3 query | PR-4 schedule | PR-5 thread | PR-7 budget |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| 1. Daily notes input | ● | ● | ● | | | |
| 2. Topics knowledge base | | ● | ● | | | |
| 3. Learning workflow | ○ | ● | ● | | ● | |
| 4. Connected-topics discovery | | ● | ● | ● | ○ | |
| 5. Live conversation room | ○ | | | | ○ | | *(see §Outlier)* |
| 6. Knock the peanut | ○ | ● | ● | | ○ | ● |
| 7. Gaps finder | | ● | ● | ○ | | |

● required · ○ benefits from

Feature 1 is the keystone — the notes corpus + a retrieval surface is
the substrate features 3, 4, 6, 7 all read. PR-1 and PR-2 are P0 for
that reason.

---

## PR-1 — Media ingestion + blob-backed artifacts  · **P0**

*Enables: 1 (keystone); feeds 3, 6, 7.*

**Need.** A path for user-supplied bytes (voice notes, notebook
photos) to enter the platform and be carried by an artifact.

**Current state.** Job input is JSON (`BaseJobInput`) and `BaseArtifact`
is JSON-only (`model_config = extra="forbid"`, persisted via
`ArtifactService.put` → `model_dump(mode="json")`). The bytes layer
already exists — `FileRepository.put_canonical_file` takes
`PutFilePayload{bytes_data, content_type, metadata}` across
local/B2/Supabase — but there is **no user-facing upload route** and no
artifact variant that points at a blob.

**Proposed shape.**
1. An **upload surface** on the control plane: either a multipart
   `POST` that lands bytes in the storage plane (mirrors the existing
   `POST /code-packages` multipart wheel upload), or signed-URL upload
   straight to the storage plane (the contract's §11 open-Q9 already
   anticipates this — signed URLs keep "bytes never traverse the
   control plane" absolute).
2. A **`storage_ref`-backed artifact** variant so an artifact can
   reference a blob instead of inlining JSON. The contract's §7 already
   names `storage_ref` as artifact metadata; the implemented
   `BaseArtifact` just hasn't needed it. Add `storage_ref` +
   `content_type` + `byte_size` as optional fields, hydrated to a signed
   read URL on `GET /artifacts/{id}`.

**Boundary (stays domain-side).** Transcription (ASR), OCR, and vision
are *domain tools* the `math-notes` wheel pulls under `[execution]`.
The platform only carries bytes and the ref.

**Cheap path.** None clean — this is genuinely missing. The `math-ui`
BFF could stash files itself and pass URLs in JSON, but that splits the
storage plane and breaks the lineage/artifact model. Build it properly.

---

## PR-2 — Cross-domain shared types + read facade  · **P0**

*Enables: 2, 3, 4, 7; helps 6.*

**Need.** A shared concept knowledge base (the `ConceptArtifact` /
`ConceptRelationArtifact` types from [`docs/features.md`](features.md)
§Math-Q&A-stabilization) consumed by qa / conversation / notes /
learning, without one domain importing another.

**Current state.** `AGENTS.md` forbids domain→domain imports
(slim-runtime isolation), and the named cross-domain facade
`mathai.workspace.*` (`MathWorkspaceClient`, `MathArtifactService`)
does **not exist yet** in the platform repo. Cross-domain *reads
already work over the API* — `GET /artifacts/{id}` is a discriminated
union over every registered artifact type — so the gap is the Python
import boundary and a shared place for the types to live, not a new
transport.

**Proposed shape.**
1. Sanction a **shared library tier** — either `mathai.workspace.*` in
   the platform `packages/core`, or a standalone `mathai-concepts`
   wheel both runtimes install — that owns artifact types more than one
   domain produces/consumes. Register once; every domain's
   `ArtifactService` picks them up.
2. A thin **read facade** (`MathArtifactService.get / list_by_type`)
   that domains call to read another domain's artifacts by ref/type
   without importing its package.

**Boundary.** The shared tier holds *types and reads only* — no domain
workflow logic crosses. Write-ownership stays with the producing domain.

---

## PR-3 — Structured artifact query (read-side)  · **P1**

*Enables: search in 1/2, recommender in 4, gaps in 7.*

**Need.** Retrieve artifacts by type / tag / time / `created_by`
without scanning, so the notes corpus and concept graph are navigable.

**Current state.** `ArtifactService.list` is thin; `GET /jobs` has rich
filters but `GET /artifacts` does not. No metadata index.

**Proposed shape.** Add a metadata/tag field to `BaseArtifact` and a
filtered `GET /artifacts?type=&tag=&created_after=&created_by=&limit=`
backed by the structured repos (Supabase indexable, local/B2
best-effort).

**Boundary — important.** Per design §13, **vector store / semantic
search is NOT a platform requirement.** Semantic / agentic search over
the corpus is domain-owned: `math-notes` stands up its own pgvector
table in the tenant storage plane and exposes a retrieval *tool*. The
platform gives only cheap *structured* filtering; embeddings never
become a built-in.

---

## PR-4 — Scheduled / triggered runs  · **P2**

*Enables: 4 (background recommender); helps 7 (periodic gaps sweep).*

**Need.** Run a job proactively on a cadence, not just on user submit.

**Current state.** Everything is submit-driven (`POST /jobs/runs/submit`).
No scheduler/cron primitive.

**Proposed shape.** A scheduling entry on the control plane: a stored
`(job_type, input_template, cron)` that the API materializes into
submitted runs.

**Cheap path (do this first).** External cron → `POST /jobs/runs/submit`.
Promote to a platform primitive only once a second domain wants it —
don't build the scheduler speculatively.

---

## PR-5 — Cross-run thread / journey grouping  · **P1**

*Enables: 3 (resumable journeys with history); helps 5, 6.*

**Need.** Group many runs over days/weeks into a resumable thread with
history — "start a learning thread, return to it, see your history."

**Current state.** The unit is a single `JobRun` plus within-run human
gates (`WAITING_INPUT ↔ RUNNING`). Nothing groups runs across time;
`created_by` exists on input but there's no thread/session entity.

**Proposed shape.** Decide between two paths up front (reversible but
cheaper to pick now):
- **Domain-modeled (recommended first):** a `LearningJourneyArtifact`
  that references run-ids + concept-ids. Zero platform change; uses
  PR-2 + PR-3 to read its own history.
- **Platform primitive:** a first-class `Session`/`Thread` object that
  groups runs. Justified only if 3, 5, and 6 all converge on needing
  it — flag, don't pre-build.

---

## PR-7 — Per-run model / budget tier  · **P2**

*Enables: 6 (knock the peanut).*

**Need.** Let a job opt into a higher effort tier — Opus, more
iterations, longer timeout — since that feature's whole premise is
"the level of tokens we're allowed to use."

**Current state.** `ExecutionPolicy` already carries timeout/retries;
model is chosen inside nodes today (e.g. `basic_agent(model=...)`).

**Proposed shape.** A `model_tier` / `effort` knob on the job input or
`ExecutionPolicy`, threaded to `deps_factory`, so the domain picks the
model + iteration cap from one place instead of hardcoding per node.
Small.

---

## Outlier — Live conversation room (feature 5): stays *outside* the platform

The batch async runner (submit → run-to-completion → result, one-way
SSE logs, store-and-resume gates) has **no realtime bidirectional
channel**, and bending it into one would violate the plane separation
(§8 explicitly excludes in-process / interactive execution from the
contract). Recommendation: **do not make this a platform requirement.**

Build the live room as a **separate realtime service** (WebSocket /
WebRTC + ElevenLabs streaming ASR/TTS), reuse the `math_conversation`
crew personae as the agent logic, and use the platform only as the
**artifact sink** — persist the transcript + any figures the room
generated when the call ends. That deposit reuses PR-1's ingest path;
no new platform primitive. The existing `math_conversation` job is a
batch panel-to-completion — good for logic, not for liveness.

---

## What deliberately stays domain-side (honoring design §13)

So the platform stays thin, none of these become platform features:

- **Embeddings / vector index / RAG** over notes, books, theorems, Lean
  mathlib — domain storage + a retrieval tool (PR-3 boundary).
- **ASR / OCR / vision** for ingestion — domain `[execution]` deps (PR-1
  boundary).
- **The recommender model** (feature 4) and **gap-extraction prompts**
  (feature 7) — ordinary domain jobs/prompts.
- **The realtime transport + voice** (feature 5) — a separate service.

---

## Priority & sequencing

1. **PR-1** (media) + **PR-2** (shared types) — P0, unblock the keystone
   `math-notes` domain and the shared concept KB.
2. **PR-3** (query) + **PR-5** (journey, domain-modeled first) — P1.
3. **PR-4** (schedule, external-cron first) + **PR-7** (budget) — P2.
4. Live room — last; separate service, not a platform item.

See [`FEATURES.md`](../FEATURES.md) for the feature descriptions and
[`docs/features.md`](features.md) for the already-designed artifact
shapes (concepts, relations, rich content) PR-2 builds on.
