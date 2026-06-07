# Dev lifecycle — keeping the two repos coherent

The platform spans two sibling checkouts:

| Repo | Role | Entrypoints |
|---|---|---|
| `mathapp` (this repo) | FastAPI backend, Python workers, job/workflow definitions | `scripts/api.sh`, `scripts/worker.sh` |
| `math-ui` | Next.js 16 frontend | `npm run dev` |

The only contract between them is **the OpenAPI schema** that FastAPI
emits. Everything else (DB shape, job state, prompt internals) is a
backend implementation detail.

---

## The contract

```
mathapp pydantic models ──► /openapi.json ──► math-ui/lib/api/schema.d.ts
                                                       │
                          (derived)        ┌───────────┴───────────┐
                                           ▼                       ▼
                              math-ui/lib/math-types.ts   math-ui/lib/workflow-types.ts
                                           │                       │
                                           ▼                       ▼
                                     UI components, hooks, BFF route handlers
```

`schema.d.ts` is **generated and committed**. PR diffs surface contract
changes; `tsc` is the gate that catches drift.

---

## The loop

When you change an API request/response shape in `mathapp`:

1. **Backend.** Edit the pydantic model (request body, response model,
   or any `JobResult` / artifact variant). Run `scripts/test.sh` until
   green.
2. **Regenerate the schema** — from `math-ui/`:
   ```bash
   npm run gen:api
   ```
   This invokes `mathapp/scripts/dump-openapi.sh` (offline export — no
   running server needed) and writes `math-ui/lib/api/schema.d.ts`.
3. **Typecheck the UI:**
   ```bash
   npx tsc --noEmit
   ```
   Errors here = consumers that need updating because the contract
   changed (renamed field, new required field, changed type, etc.).
4. **Update consumers**, then commit `schema.d.ts` together with the UI
   changes that adapt to it.

When the UI repo's `npm run gen:api:check` runs in CI, it regenerates
the schema and fails if the diff is non-empty — i.e. someone bumped the
backend without re-running codegen.

---

## What lives where

- **OpenAPI source of truth:** `mathapp/scripts/dump-openapi.sh` —
  imports `ai_platform.entrypoints.api:app` and prints `app.openapi()`.
  Used by both the math-ui codegen pipeline and any external consumer.
- **Generated TypeScript types:** `math-ui/lib/api/schema.d.ts`. **Do
  not hand-edit.**
- **Domain-facing TS types:** `math-ui/lib/math-types.ts`,
  `math-ui/lib/workflow-types.ts`. These derive from the schema and
  add UI-only narrowing (e.g. `JobStatus` literal union, tightening
  always-present-but-pydantic-optional fields like `artifact_id`).
- **Typed upstream client:** `math-ui/lib/api/client.ts` —
  `openapi-fetch` wrapper, used from server-side BFF route handlers in
  `app/api/`. Browser code does not call the upstream API directly.

---

## What stays internally consistent without codegen

These are backend-only and have their own conventions documented
elsewhere — they don't cross the wire to the UI:

- **Job definitions and workflow specs** — see [`onboarding_new_job_type.md`](onboarding_new_job_type.md).
- **Prompt registry** — see [`prompt_registry.md`](prompt_registry.md).
- **Compute backends** — see [`compute_backends.md`](compute_backends.md).

---

## Common drift scenarios

| Symptom | Cause | Fix |
|---|---|---|
| `tsc` error: property X does not exist on type Y | Backend renamed/removed a field | Update the UI consumer; re-run `gen:api` |
| `tsc` error after a clean checkout | `schema.d.ts` is stale on this branch | `npm run gen:api` and commit |
| CI `gen:api:check` fails | Backend was changed without regenerating | Run `npm run gen:api` locally and commit the diff |
| Runtime 422 from the API | Frontend sending a stale request shape | Same — regenerate, fix the call site |

The principle: **let TypeScript be loud**. Every contract change should
either fail `tsc` or fail `gen:api:check` — never silently make it to
runtime.
