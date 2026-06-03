# platform-ui

The platform's **admin SPA** — a domain-free, catalog-browser-style
control plane UI. Same shape industry uses (Airflow's DAGs view,
Temporal Web, Databricks Workspace, MLflow Tracking UI): list the
platform's primitives, drill down, ship.

This is deliberately **not** [`math-ui/`](../math-ui/). That one is a
*domain* UI — math-specific layouts, question/answer chat, LaTeX
rendering. This one knows nothing about math. It would be identical
in shape if the platform were running a different friend's domain.

## What it shows

Three catalog browsers, one per platform primitive:

- **Job Definitions** — every runnable job the platform knows about,
  with runtime + code entrypoint + last-deployed timestamp.
- **Artifact Types** — every typed output a domain has declared, with
  owning domain + class name.
- **Code Packages** — every wheel uploaded via `aiplatform deploy`,
  with sha256, size, runtime, and a download link routed through
  the BFF proxy.

Plus an **Overview** dashboard with counts.

Click any row → full JSON record in a side drawer.

## Stack

Mirror of math-ui's stack for familiarity:

- Next.js 16 (App Router) + React 19
- Tailwind 4 (no shadcn — kept this UI lean)
- `openapi-typescript` + `openapi-fetch` for the typed client
- BFF proxy at `/api/[...path]` forwards browser calls to the
  upstream platform API; the upstream URL never leaves the server.

## Run locally

```bash
cd platform-ui
npm install
npm run gen:api                              # regenerate lib/api/schema.d.ts
PLATFORM_API_URL=http://localhost:8000 npm run dev
# → http://localhost:7861
```

The `gen:api` script reads from the same source ladder as
math-ui's: `$OPENAPI_SOURCE` → `$MATHAPP_REPO/scripts/dump-openapi.sh`
→ monorepo parent → fallback to a running `http://127.0.0.1:8000`.

## Smoke-test against prod

```bash
PLATFORM_API_URL=http://mathapp-prod:8000 npm run build
PLATFORM_API_URL=http://mathapp-prod:8000 PORT=7861 \
    node .next/standalone/server.js
```

Open <http://localhost:7861>. Overview should show the live counts.

## Deploy

The Dockerfile builds a standalone Next image listening on port
**7861** (math-ui owns 7860). No compose entry today — same posture
as math-ui, which is also built but launched separately.

```bash
docker build -t platform-ui:local .
docker run --rm -p 7861:7861 \
    -e PLATFORM_API_URL=http://your-api:8000 \
    platform-ui:local
```

## Layout

```
app/
  api/[...path]/route.ts     BFF proxy → upstream PLATFORM_API_URL
  job-definitions/page.tsx   server fetch + handoff
  artifact-types/page.tsx
  code-packages/page.tsx
  page.tsx                   Overview dashboard
  layout.tsx                 header + nav + globals
components/
  CatalogTable.tsx           reusable table + JSON drawer (client)
  {JobDefinitions,ArtifactTypes,CodePackages}Table.tsx
                             per-catalog client wrapper (defines columns)
lib/
  api/{client,catalogs,schema.d.ts}.ts
                             typed openapi-fetch client + fetchers
  format.ts                  timestamps, bytes, sha shortener
```

## On-deck

What's deliberately not here yet (in priority order):

- **Jobs / runs inspector.** List + status filter + click-through to
  status + result. The API exposes `/jobs`, `/jobs/{id}`,
  `/jobs/{id}/result`, `/jobs/{id}/logs/stream`; the UI just needs
  the pages.
- **Submit job form.** Generate a form from
  `JobDefinitionRecord.input_schema` (a JSON Schema), POST to
  `/jobs/runs/submit`. Probably `react-json-schema-form` or
  `@rjsf/core`.
- **Live updates.** Today the catalog pages are `force-dynamic` SSR
  with no streaming. SSE for new rows + status changes is a
  follow-up.
