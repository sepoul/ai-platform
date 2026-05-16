# Next best steps

The platform/domain split exists on the backend (`ai_platform.*` vs
domain packages). The frontend is gradually mirroring it. This file
tracks the coherence gaps that surfaced while introducing
[`lib/platform/`](lib/platform/index.ts) and the `/workflows` index.

Keep in sibling order with the backend [NEXT_BEST_STEPS.md](../NEXT_BEST_STEPS.md) at the repo root.

---

## 1. Backend: expose a `GET /workflows` registry ✅ done

Implemented; the [/workflows](app/workflows/page.tsx) index now
fetches from `GET /workflows` and `WORKFLOW_JOB_TYPES` has been
removed. `WorkflowJobType` is now a plain `string` — type discipline
comes from "did you fetch this from the backend?" rather than a
compile-time literal.

## 2. Move `math-types.ts` into platform vs domain ✅ done

`lib/` now physically separates platform from domain:

- [lib/platform/](lib/platform/) — job lifecycle types
  ([job-types.ts](lib/platform/job-types.ts)), workflow types,
  artifact types, jobs/workflows/artifacts clients,
  active-jobs-store, BFF proxy, hooks, workflow-graph layout. Public
  barrel at [index.ts](lib/platform/index.ts).
- [lib/domains/math-qa/](lib/domains/math-qa/) — `MathQAResult` +
  artifact shapes ([types.ts](lib/domains/math-qa/types.ts)),
  `mathClient.submitQuestion` ([client.ts](lib/domains/math-qa/client.ts)),
  domain progress copy
  ([progress-copy.ts](lib/domains/math-qa/progress-copy.ts)).

The platform stays domain-agnostic: `JobStatusResponse.result: unknown`
and the math_qa job page narrows at the boundary
(`res.result as MathQAResult | null`). Domain-typed result handling
will be replaced by §3 (discriminated union) when it lands.

React components stayed in `components/{math,artifacts,workflow,...}`
— they're not lib code. A future tidy could move them under
`components/domains/math-qa/` and `components/platform/` to match.

## 3. Make `JobResult` a discriminated union over `job_type`

[JobStatusResponse.result](lib/math-types.ts) is hard-coded to
`MathQAResult | null`. The backend response *is* a discriminated union
(see `result.job_type`), but with a single domain registered the schema
collapses it to a concrete shape.

When a second domain ships, this will break silently in the codegen.
Plan now:

- At the platform level, type `result` as a discriminated union over
  every domain's result variant — generated from the OpenAPI `oneOf` /
  `discriminator`.
- Domain code narrows by `result.job_type` before reading domain
  fields.
- Hooks like [useJobPolling](lib/hooks/use-job-polling.ts) stay
  domain-agnostic; they just expose the typed `result` and let
  consumers narrow.

## 4. Surface `ExecutionPolicy` in `WorkflowSpecResponse` ✅ done

`WorkflowSpecResponse.gates: list[GateSpec]` is now on the wire, with
each entry carrying `{node_name, review_type, params}` derived from
the backend's `ExecutionPolicy`. The
[WorkflowSpecView](components/workflow/workflow-spec-view.tsx) renders
a dedicated **Execution policy** section, and the human-wait detection
in [workflow-graph.ts](lib/platform/workflow-graph.ts) now relies on
`stage.is_human_step` (which is policy-derived server-side) instead of
the old `waiting_for` string heuristic.

## 5. Generic submit form from `submit_params`

[QuestionForm](components/math/question-form.tsx) is bespoke math_qa.
The same shape is already on the wire as `WorkflowSpecResponse.submit_params`
— the platform should be able to auto-render a basic submit form
(string / number / select inputs) for any registered job type, with
domains optionally overriding via a registry of custom form
components.

This is the natural complement to step 1 (`GET /workflows` index): once
the registry is server-driven, the platform can host
`/workflows/[jobType]/run` as a generic submit page.

## 6. Platform-level `/jobs` index ✅ done

[/jobs](app/jobs/page.tsx) lists every workflow run (history view).
Backend `JobStatusResponse` gained `job_type` and `created_at` for
this use; rows group by status via shadcn `Tabs` (RUNNING /
WAITING_INPUT / SUCCEEDED / FAILED / etc.) with counts, color-coded
status badges, and click-through to domain detail pages
(`/math-qa/[jobId]` for math_qa). Unknown job types stay informational
until a domain registers a route in `JOB_TYPE_ROUTES`.

## 7a. Artifact viewer ✅ done

Implemented at [/artifacts](app/artifacts/page.tsx) +
[/artifacts/[id]](app/artifacts/[artifactId]/page.tsx). Backend
artifacts router was migrated from the math domain into
`ai_platform.api.routers.artifacts`; the GET endpoint now returns a
discriminated union over every registered domain's `BaseArtifact`
subclasses (driven by a runtime registry built from each `Domain.artifact_types`),
and the list endpoint returns lightweight summaries with `job_id` /
`artifact_type` / `limit` filters.

## 7d. Artifact-type registry view ✅ done

[/artifact-types](app/artifact-types/page.tsx) reflects every
registered `BaseArtifact` subclass — class name, owning domain, and
the field list derived from its pydantic schema. Backend at
`GET /artifacts/types`. Useful for documenting what each domain
contributes to the platform.

## 7b. Domain-renderer registry for artifacts

[ArtifactCard](components/artifacts/artifact-card.tsx) currently has a
hard-coded switch over the three math_qa artifact types, with a JSON
fallback for anything else. Domains should register their own renderer
components keyed by `artifact_type` — same pattern as the planned
generic submit form (§5). Until then, every new domain artifact lands
in the JSON fallback.

## 7c. Prompts UI

Backend exposes `/prompts`, `/prompts/{name}`, `/prompt-executions` —
no UI yet. Same platform-page pattern as `/workflows` and
`/artifacts`: a list + detail view rendered straight from the OpenAPI
shapes. See [prompt_registry.md](../docs/prompt_registry.md)
for the backend model.

## 8. Audit `components/workflow/` for hidden math_qa coupling

The workflow components were named generically before the platform
split was introduced. Verify
[WorkflowJobRunner](components/workflow/workflow-job-runner.tsx),
[WorkflowGraphView](components/workflow/workflow-graph-view.tsx), and
[WorkflowStepperView](components/workflow/workflow-stepper-view.tsx)
truly have no domain assumptions, and move them under
`components/platform/workflow/` once the directory split lands.
