# @aiplatform/sdk

TypeScript client for ai-platform. Mirror of the Python
[`PlatformSession`](../packages/core/src/ai_platform/session/session.py)
plus a Next.js BFF proxy helper.

Consumers (math-ui, platform-ui, any friend's domain UI) install
this once and stop hand-rolling `openapi-fetch` + a BFF proxy +
per-repo `gen-api.sh`. The OpenAPI schema is generated **inside
this package**, committed to `dist/` at build time, and re-exported
as types so downstream consumers get them transitively via
`npm install`.

## Surface

```ts
import {
  PlatformSession,           // session object
  JobHandle,                  // submit + wait + result handle
  createBffMethods,           // Next.js BFF route handler
  type JobDefinitionRecord,   // typed catalog records
  type ArtifactTypeRecord,
  type CodePackageRecord,
  type JobStatusResponse,
  type JobResultResponse,
} from "@aiplatform/sdk";

const session = new PlatformSession({ apiUrl: "http://platform:8000" });
const jds = await session.listJobDefinitions();
const handle = await session.submitJob("math_qa", { question_text: "..." });
const result = await handle.result({ timeoutMs: 120_000 });
```

### Next.js BFF proxy

```ts
// app/api/[...path]/route.ts
import { createBffMethods } from "@aiplatform/sdk";

export const { GET, POST, PUT, DELETE, PATCH } = createBffMethods({
  upstreamUrl: process.env.PLATFORM_API_URL!,
});
```

## Build / consume

The SDK ships compiled `dist/` output. Consumers add it to their
`package.json`:

```jsonc
{
  "dependencies": {
    "@aiplatform/sdk": "file:../sdk-ts"
  }
}
```

…and pin `install-links=true` in their `.npmrc` so the file: dep is
hard-copied (Next 16's Turbopack resolver can't follow symlinked
file: deps).

In the consumer's `package.json`, add a `prebuild` (and ideally
`predev`) hook so the SDK is built before Next bundles:

```json
{
  "scripts": {
    "sdk:build": "npm --prefix ../sdk-ts run build",
    "predev": "npm run sdk:build",
    "prebuild": "npm run sdk:build"
  }
}
```

## Regenerate the schema after API changes

```bash
cd sdk-ts
npm run gen:api           # rewrites src/schema.d.ts
npm run build             # rewrites dist/
```

`gen:api` resolves the OpenAPI source the same way
[math-ui's gen-api script](../math-ui/scripts/gen-api.sh) does:
`$OPENAPI_SOURCE` → `$MATHAPP_REPO/scripts/dump-openapi.sh` →
monorepo parent → `http://127.0.0.1:8000/openapi.json` fallback.
