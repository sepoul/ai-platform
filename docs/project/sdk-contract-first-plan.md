# Contract-first artifacts + automated SDK

Plan to kill the SDK-regen hassle and let a domain develop backend +
frontend **in parallel**, against typed contracts, before deploying
anything. The catalog you already have is the registry; the new pieces
are small.

> Status: design. Build order at the bottom. Companion to
> [`platform-requirements.md`](platform-requirements.md) (PR-2 shared
> types rides on this).

---

## The reframe

- **Artifacts = the contract.** Declared early, consumed by both UIs
  (TS types), the producing domain (pydantic), and other domains
  (cross-domain reads).
- **Jobs = the implementation.** The wheel + execution graph. Ships
  when ready.
- **The catalog = the durable seam + registry.** Deploy writes JSON
  Schema to it (runtime); SDK generation reads from it (build-time).
  They never share a live process.

Today `aiplatform deploy` welds contract + implementation into one
shot, which traps the contract behind the implementation and serializes
frontend behind backend. We pull the contract out front.

The backend **already separates them** — three independent tables +
endpoints:

| Concern | Endpoint | Table | Holds |
|---|---|---|---|
| Contract | `POST /artifact-types` | `artifact_types` | `json_schema` (from `model_json_schema()`) |
| Implementation | `POST /job-definitions` | `job_definitions` | input/result schema, entrypoints |
| Code | `POST /code-packages` | `code_packages` | the wheel bytes |

`aiplatform deploy` just calls all three. Declaring an artifact type
needs **no wheel and no job**.

---

## Part A — Split the deploy (`aiplatform declare-artifacts`)

New thin CLI command: posts **only** the artifact-type JSON Schemas to
the catalog (reuses the existing `/artifact-types` endpoint + the
existing `build_artifact_type_record(cls)` reflector). No wheel upload,
no job definition.

```bash
# Publish the contract early — before the job exists.
aiplatform declare-artifacts --bundle packages/<domain>/bundle.toml \
                             --api-url http://<platform>:8000
```

Effect: contract lands in the catalog → SDK regen → **both sides
unblock**:

```
1. write the artifact (pydantic BaseArtifact subclass)        ← contract
2. aiplatform declare-artifacts        → catalog updated       ← published
3.    └─► SDK regen (local for dev / CI for publish)           ← types everywhere
4. IN PARALLEL:
     backend: build the job that PRODUCES it
     frontend: build the UI that CONSUMES it (typed; can mock instances)
5. aiplatform deploy (wheel + job)                             ← implementation ships
```

Nuance: declaring gives the **contract everywhere** (types, mocks,
cross-domain reads). Serving *real instances* over `GET /artifacts/{id}`
still needs the wheel (the pydantic class to hydrate). That's just the
contract↔implementation line, exactly as intended.

---

## Part B — Catalog-driven SDK generation

The bug today: `sdk-ts/src/schema.d.ts` is generated from **one running
instance's `/openapi.json`**, whose unions only include the domains
*that instance imported at boot*. The platform's local/CI instance has
only `_demo`, so a naive regen drops the `math_*` types.

Fix: generate from the **catalog** (every deployed type), not an
instance.

- **Phase 1 (ship first):** split into a privileged "produce the source"
  step and a privilege-free "transform" step, so **CI never touches the
  private network** (it doesn't join the tailnet and holds no secrets):
  1. An operator on the tailnet runs `aiplatform snapshot-openapi
     --api-url http://mathapp-prod:8000` → writes the full
     `sdk-ts/openapi.snapshot.json` → commits it.
  2. That commit triggers a workflow that regenerates `schema.d.ts` from
     the committed snapshot and opens a PR. Pure transform — the box is
     never reached from CI.
- **Phase 2 (instance-proof):** add `GET /sdk/openapi.json` that
  *assembles* a complete OpenAPI from the catalog's `json_schema` +
  `input_schema` + `result_schema` rows — servable even by a
  domain-less instance. The existing `openapi-typescript` consumes it
  unchanged. Real work here is `$defs` namespacing/dedup across domains
  (two domains could both define a `Figure`).

---

## Part C — Distribution: how a domain repo gets an up-to-date SDK

Today `@aiplatform/sdk` is consumed via a **`file:` path** to a sibling
checkout (`math-app/math-ui` → `file:../../ai-platform/sdk-ts`). Fine
for co-located dev, useless for a friend without your checkout.

Recommendation — **two modes**:

### 1. Published artifact → GitHub Packages (the "npm-like" answer)

Publish `@aiplatform/sdk` to **GitHub Packages** (private npm registry,
free for the org, GitHub-native). CI publishes a new version whenever
the schema changes (version = date or short-sha, or semver-on-contract-
change).

Domain repo consumes it like any dep:

```ini
# .npmrc in the domain repo
@aiplatform:registry=https://npm.pkg.github.com
//npm.pkg.github.com/:_authToken=${GITHUB_TOKEN}
```

```jsonc
// package.json
"dependencies": { "@aiplatform/sdk": "^<version>" }
```

```bash
npm update @aiplatform/sdk     # pull the latest contract
```

### 2. Local inner loop → instant types, zero deploy

For "syntax highlighting before ever deploying," override the published
dep with a local link so the UI sees **locally regenerated** types:

```bash
# in the domain repo, point at the sibling SDK (or `npm link`)
npm i @aiplatform/sdk@file:../../ai-platform/sdk-ts
```

Inner loop for a **new** artifact:

```bash
# 1. write the pydantic artifact in your domain package
# 2. run the platform locally WITH your domain registered
docker compose up            # local platform + your domain
# 3. regenerate types from the LOCAL api (not prod)
OPENAPI_SOURCE=http://localhost:8000/openapi.json \
  npm --prefix ../ai-platform/sdk-ts run gen:api
npm --prefix ../ai-platform/sdk-ts run build
# 4. types light up in the editor → build UI + job in parallel
```

(`math-ui` already runs `sdk:build` in its `predev`/`prebuild`, so a
rebuilt sibling SDK is picked up automatically.)

So: **published mode** keeps consumers (and friends) current via a
normal dep bump; **local mode** gives the domain dev instant types from
their own pydantic, before anything is deployed.

---

## Trigger wiring (the "magic", without extending the trust boundary)

```
operator (already on the tailnet)
  aiplatform snapshot-openapi --api-url http://mathapp-prod:8000
        │ writes sdk-ts/openapi.snapshot.json
        ▼ git push
push (paths: openapi.snapshot.json)  → ai-platform CI
        │  pure transform — no tailnet, no secrets
        ├─ regenerate schema.d.ts from the committed snapshot (Part B)
        ├─ open a PR with the diff
        └─ publish @aiplatform/sdk to GitHub Packages (Part C, move 3)
```

The only step that reaches the box is the snapshot dump, run by someone
already trusted to reach it. CI joins no private network and holds no
secrets. Decoupled: a regen failure never blocks a domain going live.

> Earlier sketch had CI fetch the OpenAPI from the box over Tailscale —
> rejected: it puts a GitHub runner inside the private perimeter. The
> snapshot/push split avoids that entirely.

---

## Build order

1. **`aiplatform declare-artifacts`** CLI (Part A) — small, reuses
   `/artifact-types`. Unblocks parallel dev immediately. ✅
2. **Snapshot-driven regen workflow** (Part B Phase 1) — `aiplatform
   snapshot-openapi` + a workflow that regenerates `schema.d.ts` from the
   committed snapshot and opens a PR. No CI tailnet/secrets. ✅
3. **Publish to GitHub Packages** (Part C mode 1) + document the local
   link loop (mode 2).
4. **`GET /sdk/openapi.json`** assembler (Part B Phase 2) — makes
   generation instance-proof and lets the snapshot come from the catalog
   directly; tackle `$defs` namespacing.
5. (Optional) fold the snapshot+push into a one-shot `aiplatform deploy`
   convenience for operators with repo write access.
