# SDK & types: the dev loop

The platform publishes one typed client — `@aiplatform/sdk`
(`sdk-ts/`) — generated from the FastAPI OpenAPI schema. Both UIs consume
it: `platform-ui` (in this repo) and a domain UI such as
`math-app/math-ui`. Its committed source of truth is
`sdk-ts/src/schema.d.ts`.

This guide is the **developer loop**: how to get up-to-date types into
your editor — including **before you deploy anything** — and how the
published SDK stays in sync automatically.

See also [Deploy a domain](deploy-a-domain.md) and
[Typed clients (OpenAPI / SDK)](../reference/typed-clients.md) for the
codegen mechanics.

---

## The model: contract-first

Artifacts are a **contract**; jobs are an **implementation**. The catalog
stores each artifact type as plain JSON Schema
(`artifact_types.json_schema`), independent of any job that produces it.
So you can publish the contract early and let the producing job (backend)
and the consuming UI (frontend) be built **in parallel** against typed
shapes — neither blocks the other.

```
write pydantic artifact ─▶ declare it ─▶ types regenerate ─▶ build job + UI in parallel ─▶ deploy job
        (contract)                         (SDK)                                              (implementation)
```

Publish just the contract — no wheel, no job — with:

```bash
aiplatform declare-artifacts --bundle bundle.toml --api-url http://<platform>:8000
```

---

## Local mode — types before you deploy anything

The inner loop. You get full type/syntax highlighting from your own
pydantic models without deploying to any shared environment.

**1. Point your UI's SDK at a local checkout** (so it sees locally
regenerated types). In the domain UI's `package.json`:

```jsonc
"@aiplatform/sdk": "file:../../ai-platform/sdk-ts"   // sibling checkout (or: npm link)
```

`math-ui` already runs `sdk:build` in its `predev`/`prebuild`, so a
rebuilt sibling SDK is picked up on the next `npm run dev`.

**2. Get a complete OpenAPI locally** — two ways:

=== "Run the platform locally with your domain"

    ```bash
    # in your domain repo (or ai-platform): boot the stack with your domain
    docker compose up
    # regenerate from the LOCAL api — not prod, no deploy
    OPENAPI_SOURCE=http://localhost:8000/openapi.json \
      npm --prefix ../ai-platform/sdk-ts run gen:api
    npm --prefix ../ai-platform/sdk-ts run build
    ```

=== "Offline dump (no server)"

    ```bash
    # in ai-platform: build the app in-process and dump its schema
    ./scripts/dump-openapi.sh /tmp/openapi.json
    OPENAPI_SOURCE=/tmp/openapi.json npm --prefix sdk-ts run gen:api
    npm --prefix sdk-ts run build
    ```

**3. (Contract-first)** To get types for an artifact whose job isn't
written yet, `declare-artifacts` to your local (or a shared) catalog,
then regenerate — the schema appears without any wheel or job. Now build
the UI against it and mock instances until the producing job ships.

> Your inner loop never waits on CI or on another repo. You regenerate
> from your own running/declared catalog and the types light up
> immediately.

---

## Published mode — consume the versioned package (npm)

`@aiplatform/sdk` publishes to **npmjs.com** (public). Consumers depend on
a real version instead of a sibling `file:` checkout — no filesystem
coupling, reproducible across machines + CI:

```jsonc
// package.json in the consuming repo (e.g. math-app/math-ui)
"dependencies": {
  "@aiplatform/sdk": "^0.1.1"
}
```

```bash
npm update @aiplatform/sdk     # pull the latest contract
```

It's a **public** package, so no `.npmrc` / auth is needed to install.

**Cutting a release** (`.github/workflows/sdk-publish.yml`): bump
`sdk-ts/package.json` `"version"`, commit to main, then tag + push:

```bash
git tag sdk-v0.1.2 && git push origin sdk-v0.1.2   # tag must match the version
```

The tag triggers the publish workflow. One-time operator setup: own the
`@aiplatform` scope on npm (create the free `aiplatform` org) and add an
npm **Automation** token as the `NPM_TOKEN` repo secret. See the workflow
header.

> **Migrating off `file:`** — math-ui currently uses
> `"@aiplatform/sdk": "file:../../ai-platform/sdk-ts"`. Switch it to
> `"^0.1.1"` (and drop any local-path `.npmrc` scope line) once the first
> version is published.

---

## How `schema.d.ts` stays in sync (automated)

Two steps, deliberately split so **CI never touches your private
network**:

**1. Snapshot** — needs the box, so *you* run it (you're on the tailnet):

```bash
aiplatform snapshot-openapi --api-url http://mathapp-prod:8000
git commit -am "chore: refresh openapi snapshot" && git push
```

This writes `sdk-ts/openapi.snapshot.json` — the full OpenAPI of the
deployed catalog (every platform + domain type).

**2. Regenerate** — no privileged access, so CI does it: committing the
snapshot triggers the *Regenerate SDK schema* workflow, which transforms
the committed JSON into `sdk-ts/src/schema.d.ts` and opens a PR.
Consumers pick it up on their next build / dependency bump.

The only step that reaches the box is the snapshot dump, run by someone
already trusted to reach it; CI does a pure transform — no tailnet, no
secrets. A later `GET /sdk/openapi.json` assembler will be able to
produce the snapshot from the catalog directly. See
`.github/workflows/sdk-regen.yml`.

---

## The post-split gotcha (do not hand-regen carelessly)

This repo's local API boots only the synthetic `_demo` domain. So a naive
`gen:api` against a `_demo`-only instance **silently drops** the `math_*`
domain types that `math-app/math-ui` imports — the diff shows large
deletions. Always regenerate from a source that has **every** domain
registered (a full deployment, or the offline dump of a local stack that
includes your domain). The automated workflow guards against this by
refusing to commit a schema with no domain types; the warning in
`sdk-ts/scripts/gen-api.sh` says the same.
