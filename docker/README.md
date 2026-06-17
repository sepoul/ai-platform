# docker/

Container build files for the platform images.

The **build context is the repo root** (the Dockerfiles `COPY packages/`,
`instructions/`, `supabase/` …), so reference them with `-f docker/Dockerfile.<x>`
while keeping `context: .`. Compose (`build.dockerfile:`) and CI
(`.github/workflows/build-image.yml` `file:`) already do this.

| File | Image | Role |
|---|---|---|
| `Dockerfile.api` | `aiplatform-api` | control plane (FastAPI; engine-free) |
| `Dockerfile.worker` | `aiplatform-worker` | virgin execution plane (no domain code) |
| `Dockerfile.worker-domain` | — | reference template: chain a domain wheel on top of the virgin worker (not used by CI; tenants build their own) |

**Why compose + `.dockerignore` stay at the repo root:** `docker compose`
resolves them there, the prod box's `redeploy.sh` references the root compose
paths, and `.dockerignore` must sit at the build-context root (repo root) to
apply.
