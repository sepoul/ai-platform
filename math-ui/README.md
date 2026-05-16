---
title: Ui Next
emoji: ⚡
colorFrom: pink
colorTo: blue
sdk: docker
pinned: false
license: apache-2.0
short_description: Next JS UI for ai-platform
---

Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference

## Runtime environment variables

Set these in your Hugging Face Space variables/secrets:

- `AI_PLATFORM_API_URL` (required): Base URL for the upstream backend API.
- `HF_TOKEN` (optional secret): Bearer token forwarded by API proxy routes.
- `NEXT_PUBLIC_WORKSPACE_API_URL` (optional): Frontend API base URL.
  - Default is `/api/mock` (recommended for HF Spaces).
  - For local development, you can set `NEXT_PUBLIC_WORKSPACE_API_URL=http://localhost:3000/api/mock`.

## API codegen

The TypeScript types in `lib/api/schema.d.ts` are generated from the
upstream FastAPI app's OpenAPI schema (`mathapp`). Domain-facing types
in `lib/math-types.ts` and `lib/workflow-types.ts` derive from it, so
contract drift surfaces as a TypeScript error.

```bash
npm run gen:api          # regenerate lib/api/schema.d.ts
npm run gen:api:check    # CI-friendly: regenerate + fail if diff
```

Source resolution order (first match wins):
1. `OPENAPI_SOURCE=<file-or-url>` — explicit override.
2. `MATHAPP_REPO=<path>` (or, in this monorepo, the parent dir `..`) —
   runs the backend's `scripts/dump-openapi.sh`. **No server needed.**
3. `http://127.0.0.1:8000/openapi.json` — fall back to a running
   `scripts/api.sh`.

Commit the regenerated `lib/api/schema.d.ts` whenever the API contract
changes; PR diffs make the contract change reviewable.
