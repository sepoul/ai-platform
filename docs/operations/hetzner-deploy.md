# Deployment — single Hetzner box

A pragmatic plan for getting the stack onto one Hetzner VM, reachable
only from your laptop, with as little moving infrastructure as the
problem allows. Single-tenant, single-developer. Not a multi-region
zero-downtime story; that's a different document.

> **Status (2026-05-15): steps 1–4 live end-to-end.** Box
> `mathapp-prod` (CX23, Falkenstein) is provisioned via
> `cd infra/hetzner && terraform apply`. App deploy runs from a
> GHCR-built images — GitHub Actions builds on push to `main` and
> publishes the three split images
> (`ghcr.io/sepoul/aiplatform-{api,worker,worker-crewai}:latest`); the box
> pulls them via
> [`infra/hetzner/scripts/redeploy.sh`](../infra/hetzner/scripts/redeploy.sh).
> Step 6's Celery wiring is implemented — including per-runtime queue
> routing (default vs crewai, issue #66) — and runs as a clean local
> mode (`scripts/compose-celery.sh up -d`, no poll/celery race) with a
> committed broker round-trip test (`scripts/test-celery.sh`). The prod
> flip + rollback was **rehearsed on the box (`mathapp-prod`) 2026-06-29
> and passed** (issue #68) — see §6 for the validated recipe. `poll`
> remains the prod default. The manual
> provisioning steps below are now the *reference* — the day-to-day
> path is `terraform apply` then `redeploy.sh`. See
> [infra/hetzner/README.md](../infra/hetzner/README.md).

---

## Topology

```
┌──────────────┐                                ┌──────────────────────┐
│   laptop     │ ── tailnet (WireGuard) ────▶  │   Hetzner CX22       │
│              │                                │                      │
│  next dev    │                                │  docker compose:     │
│  browser     │   http://<tailnet-ip>:8000 ▶  │   - api (uvicorn)    │
│              │   http://<tailnet-ip>:3000 ▶  │   - worker           │
└──────────────┘                                │   - (math-ui later)  │
                                                └──────────┬───────────┘
                                                           │
                                                           │ psycopg + httpx
                                                           ▼
                                                ┌──────────────────────┐
                                                │  Supabase (eu-west-1) │
                                                │   public.*  tables   │
                                                │   app-data  bucket   │
                                                └──────────────────────┘
```

Two layers of access control, each sufficient on its own:

- **Tailscale** — the box has no public services. The API listens on
  `0.0.0.0:8000` *inside* the docker network; on the host it's only
  reachable via the tailnet interface. Only devices in your tailnet
  can route to it.
- **Hetzner Cloud Firewall** — drop everything except SSH from your
  tailnet, as belt-and-braces against the day Tailscale is
  misconfigured.

No auth on the API itself. The reachability surface *is* the auth.

---

## Why not just an IP allowlist?

It works until your home/coffee-shop/mobile IP changes, and then you
re-edit the firewall rules. Tailscale gives you a stable identity
(your tailnet IPs) regardless of where the laptop sits, and the
control plane is Tailscale's problem. Free for personal use up to
100 devices.

If you'd genuinely rather not run Tailscale, use Hetzner Cloud
Firewall with `Source = your current /32` for both SSH (22) and the
API (8000). Same security posture, more maintenance.

---

## Step 1 — Smoke-test docker compose locally first

You haven't run the compose stack yet. Do this before touching
Hetzner — every problem you'd hit on the box will hit you here
first, on a machine where you can `docker compose logs -f` without
ssh.

```bash
# In mathapp/. .env is already populated.
docker compose build
BACKEND=supabase docker compose up   # or BACKEND=local for the dead-simple case
```

What to look for:

- API logs end with `Application startup complete` and `Uvicorn
  running on http://0.0.0.0:8000`.
- `curl -fsS http://localhost:8000/health` returns 200.
- Worker logs show poll-loop iterations without exceptions.
- `curl -s http://localhost:8000/jobs | jq length` returns your
  cleaned 8 jobs (when `BACKEND=supabase`).

Tear down with `docker compose down -v` if you want to nuke the
named volume too.

---

## Step 0 — Your laptop

Tailscale on the laptop is a **host install**, not a docker container.
The whole point of the tailnet is to give the host kernel a route to
`100.x.y.z` addresses; a sidecar container can't do that for your
browser.

### macOS

```bash
brew install --cask tailscale       # GUI menubar app + bundled CLI
open -a Tailscale                   # log in once; pick the same
                                    # account you'll use for the box
```

Add the CLI to PATH (the cask installs it inside the app bundle):

```bash
# zshrc / bashrc
export PATH="/Applications/Tailscale.app/Contents/MacOS:$PATH"
```

Sanity-check:

```bash
tailscale status                    # should list at least your laptop
tailscale ip -4                     # your laptop's 100.x.y.z
```

### Linux / Windows

Same idea — install the OS-native package
([linux instructions](https://tailscale.com/download/linux),
[windows](https://tailscale.com/download/windows)), log in,
`tailscale status`. Rest of the doc is platform-agnostic.

### What this gives you

Once the box is on the tailnet (step 3):

- `ssh root@<server_name>` works because Tailscale ships
  MagicDNS — names auto-resolve inside the tailnet without a
  `/etc/hosts` edit.
- `http://<server_name>:8000/health` from the browser hits the API
  without exposing it publicly.
- `tailscale ssh root@<server_name>` skips the SSH key altogether —
  Tailscale handles auth at the identity layer.

If MagicDNS is off (Tailscale admin → DNS), substitute the
`100.x.y.z` IP shown in `tailscale status`.

### Helper

```bash
infra/hetzner/scripts/connect.sh    # prints SSH commands + URLs
                                    # for the current tofu output
```

---

## Step 2 — Provision the box

> **Automated path:** [infra/hetzner](../infra/hetzner) provisions the
> server, SSH key, firewall, and cloud-init bootstrap (docker +
> Tailscale) in a single `tofu apply`. The console steps below are the
> reference for what the IaC produces; use them only if you want to
> hand-roll one box once.

Hetzner Cloud → Add Server:

| Field | Value |
|---|---|
| Image | Ubuntu 24.04 |
| Type | CX22 (2 vCPU, 4 GB, 40 GB SSD, ~€4.50/mo) |
| Location | Falkenstein or Nuremberg (closest to Supabase `eu-west-1`) |
| SSH key | Paste your laptop's `~/.ssh/id_ed25519.pub` |
| Firewall | Create new: see step 3 |
| Cloud-init | Optional; can do everything manually first time |

Don't bother with the Hetzner Docker image; install docker yourself
so the box matches what's documented here.

```bash
# From your laptop, after the server is up.
ssh root@<server-ip>

# Inside the box.
apt update && apt upgrade -y
apt install -y docker.io docker-compose-v2 git
systemctl enable --now docker
```

---

## Step 3 — Lock down with Tailscale + Hetzner Cloud Firewall

> **Automated path:** the firewall and Tailscale install are both
> handled by [infra/hetzner](../infra/hetzner). Supply
> `tailscale_auth_key` in `terraform.tfvars` to skip the interactive
> `tailscale up` and have the box join the tailnet on first boot.

### Tailscale on the box

```bash
# On the box.
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --ssh                      # opens an auth URL; click from laptop
tailscale ip -4                          # note the 100.x.y.z address
```

`--ssh` means you can `ssh root@<tailnet-ip>` from the laptop and
skip public SSH entirely; Tailscale validates the connection at the
identity layer.

### Hetzner Cloud Firewall

Apply to the server. Two inbound rules; everything else dropped:

| Direction | Protocol | Port | Source | Purpose |
|---|---|---|---|---|
| In | TCP | 22 | `<your laptop public IP>/32` | bootstrap SSH only |
| In | ICMP | — | `0.0.0.0/0` | ping for liveness |

Notice: **no rule for port 8000**. The API is unreachable from the
public internet by design. The browser hits the API at
`http://<tailnet-ip>:8000` once Tailscale is up; that traffic doesn't
cross the public internet.

Once Tailscale is verified working, you can delete the public SSH
rule too — `tailscale ssh` handles everything from there.

---

## Step 4 — Ship the app

The image is built off-box by CI
([`.github/workflows/build-image.yml`](../.github/workflows/build-image.yml))
and published to GHCR. The box's job is: clone the repo (for the
compose files + redeploy script), drop a `.env`, run `redeploy.sh`.

```bash
# On the box, after docker + tailscale.
ssh root@mathapp-prod
cd /srv
git clone https://github.com/sepoul/ai-platform.git mathapp
cd mathapp
```

From the laptop, scp **`.prodenv`** (the prod env source-of-truth) to the
box *as* `.env`. Keep two local files, neither committed: `.env` for
compose dev (Supabase `test` schema + `app-data-test`) and `.prodenv` for
the box (`public` + `app-data`). **Never scp the dev `.env`** — prod would
then run against the `test` schema. Template: `.prodenv.example`.

```bash
scp .prodenv root@mathapp-prod:/srv/mathapp/.env
ssh root@mathapp-prod 'chmod 600 /srv/mathapp/.env'
```

The box `.env` (your `.prodenv`) must include:

- `BACKEND=supabase`
- `SUPABASE_SCHEMA=public` — set **explicitly** (empty would also resolve to
  `public`, but being explicit keeps the prod/dev split unambiguous)
- `SUPABASE_BUCKET=app-data`
- `ANTHROPIC_API_KEY=…`
- `LOGFIRE_TOKEN=…` (required — `basic_agent.py` calls `logfire.configure()` at import time)
- `SUPABASE_URL=…`
- `SUPABASE_SECRET_KEY=…`
- `SUPABASE_CONNECTION_STRING=…`

Boot the stack:

```bash
ssh root@mathapp-prod 'cd /srv/mathapp && infra/hetzner/scripts/redeploy.sh'
```

`redeploy.sh` runs `docker compose -f docker-compose.yml -f
docker-compose.prod.yml --profile ui --profile crewai pull && up -d`,
then prunes dangling images. The compose override pins each service to
its split image (`aiplatform-api`, `aiplatform-worker` (virgin), `aiplatform-worker-mathqa`, `aiplatform-worker-mathconversation`)
at `:latest` (or `${IMAGE_TAG}` if exported) — no build happens on the box.

**Both workers run simultaneously.** The `worker` container serves the
`default` runtime (pydantic_ai + Logfire stack) and `worker-crewai`
serves the `crewai` runtime (crewai\[anthropic\]); they are not
swappable. Domain wheels arrive at boot via the CodePackage catalog
([architecture.md §6](../architecture.md)). Storage and compute
backends are still pick-one (`BACKEND`, `COMPUTE` env vars).

From the laptop on the tailnet:

```bash
curl -fsS http://mathapp-prod:8000/health
curl -s   http://mathapp-prod:8000/jobs | jq length
```

Should match your local dev's view of the Supabase data. Secret
rotation, `.env` updates, and the threat model live in the gitignored
`local/security.md` on each operator's laptop.

---

## Step 5 — UIs

Two UIs ship out of the box:

- **platform-ui** (domain-free admin SPA) is in this repo. The prod
  compose's `ui` profile brings it up on host port 3001.
- **A domain UI** (math-ui in the reference math-app deployment)
  comes from the domain repo's CI: it builds the image as
  `ghcr.io/<org>/<your-domain-ui>:latest` and the prod compose
  pulls it like any other image. See
  [`../guides/deploy-a-domain.md`](../guides/deploy-a-domain.md).

`redeploy.sh` brings up the `ui` profile by default, so a fresh
deploy gets both UIs:

```bash
ssh root@mathapp-prod 'cd /srv/mathapp && infra/hetzner/scripts/redeploy.sh'
# platform-ui: http://<box-tailnet-ip>:3001
# domain ui:   http://<box-tailnet-ip>:3000   (if a domain repo deployed one)
```

For public access (laptop not on the tailnet), front the API with
Caddy / nginx terminating TLS, then put domain auth in front.
Deferred until needed.

---

## Step 6 — Optional: switch from poll to Celery on the same box

### Why bother

The default `COMPUTE=poll` worker discovers new jobs by polling the
repo every `WORKER_INTERVAL` seconds (5 by default). On Supabase
that's a `SELECT` against the indexed `jobs.status` column every five
seconds — cheap, but every submitted job waits ~2.5s on average
before a worker even *looks* at it. For a single-developer
single-tenant workload that's fine; once you're showing the UI to
anyone else the lag feels janky.

`COMPUTE=celery` flips the model:

- API submits → calls `enqueue(job_id)` → Celery pushes to Redis →
  worker picks up *immediately*. Sub-second latency.
- Worker crash → job stays in the Redis queue (durable with AOF) and
  the next worker picks it up. Today's poll worker has the same
  property because the repo *is* the queue, but Celery makes
  failure-mode reasoning explicit.
- Adding a second worker tomorrow becomes a one-line compose change
  (`deploy.replicas: 2`) instead of a redesign. Single-box for now
  is the stepping stone, not the destination.

What it doesn't fix: the
[§7b debt](../NEXT_BEST_STEPS.md) — the executor still doesn't pass
`expected_version` when writing back state, so concurrent workers
on the same job can still race. Worth knowing before turning on
multi-worker.

### Topology with Celery

```
┌──────────────┐                  ┌──────────────────────────────────────┐
│   laptop     │ ── tailnet ─▶    │   Hetzner CX22                       │
│              │                  │                                      │
│              │ :8000 ▶ api ─────┼─enqueue(runtime.default)─▶ redis     │
│              │         │        │                             │  │     │
│              │         └────────┼─enqueue(runtime.crewai)──▶  │  │     │
│              │                  │                       ┌─────┘  └────┐│
│              │                  │                       ▼             ▼│
│              │                  │              celery-worker   celery-worker-crewai
└──────────────┘                  │                  │ (default)    │ (crewai)
                                  │                  └──────┬───────┘
                                  │                  psycopg + httpx
                                  │                         ▼
                                  │                  Supabase eu-west-1
                                  └──────────────────────────────────────┘
```

New containers next to `api`: `redis` plus **one celery consumer per
runtime** — `celery-worker` (default) and `celery-worker-crewai`
(crewai). The poll `worker` / `worker-crewai` stay behind the
`poll` / `crewai` profiles, so a celery-mode bring-up
(`COMPOSE_PROFILES=celery`, which `scripts/compose-celery.sh` pins)
simply doesn't include them — nothing to manually stop, and you flip
back by switching profiles.

### Runtime routing (default vs crewai)

Prod splits runtimes across worker pools with disjoint dependency
stacks — `default` (pydantic_ai: math_qa, math_notes) vs `crewai`
(CrewAI: math_conversation) — because the two can't share one
interpreter (otel-sdk pin conflict; see
[`runtimes.py`](../../packages/core/src/ai_platform/jobs/runtimes.py)).
A single Celery pool therefore can't serve every runtime. The flip-on
implements **Option A — per-runtime Celery queues** (issue #66), which
mirrors the two-poll-worker topology:

- **One queue per runtime.** `celery_queue_for_runtime(runtime)` →
  `runtime.<runtime>` (`runtime.default`, `runtime.crewai`). Centralised
  in [`compute/celery.py`](../../packages/core/src/ai_platform/compute/celery.py)
  so producer and consumer can't drift on the name.
- **Producer (API) routes by runtime.** `CeleryComputeBackend.enqueue`
  resolves the job's `runtime_selector` from the JobDefinition catalog
  and `apply_async(..., queue=runtime.<runtime>)`. Unknown/unreachable
  runtime → default queue, where the default consumer fails fast on an
  unservable `job_type` rather than silently dropping it.
- **Consumer (worker) scoped by `WORKER_RUNTIME`.** Each celery worker
  serves exactly one runtime: it registers only that runtime's domains
  (catalog discovery + cold-boot fallback, same as the poll worker) and
  consumes only `runtime.<WORKER_RUNTIME>` (derived `task_default_queue`,
  see [`celery_app.py`](../../packages/worker/src/ai_platform/entrypoints/celery_app.py)).
  So the `crewai` pool — which lacks the pydantic_ai stack — never
  receives a `default` job it couldn't import, and vice versa.

Net effect: a `math_conversation` submit lands on `celery-worker-crewai`;
a `math_qa` / `math_notes` submit lands on `celery-worker`. Adding a new
runtime later is one more queue + one more consumer, no producer change.

### Status

> **Validated on the box (`mathapp-prod`) 2026-06-29 — PASS ✅** (issue #68).
> The flip + rollback below were rehearsed end-to-end against
> `main`@d30f4aa (which also ships the #62 hang-fix: pool keepalives +
> `WORKER_JOB_LEASE_TTL_S=900`). Evidence captured on the box:
>
> - **default `math_qa`:** picked up ~1.8 s after submit → RUNNING → review
>   gate → approved → SUCCEEDED — i.e. **both** the submit *and* the review
>   enqueue paths went through the broker.
> - **crewai `math_conversation`:** picked up ~1.2 s → SUCCEEDED, routed to
>   `runtime.crewai`; the **default consumer saw it 0 times** (per-runtime
>   isolation confirmed).
> - **redis:** `appendonly yes`, no `ports:` mapping (internal-only); the
>   Hetzner Cloud Firewall blocks 6379 too.
> - **install-once (#73)** held on the box — both prefork children of each
>   consumer served the full runtime set, no `google/_upb` boot race.
> - **rollback was clean:** `api` back to `compute=poll`, the poll workers
>   reconnected, and no stray celery/redis containers were left behind.
>
> `COMPUTE=poll` stays the prod default; this is a *flip-on-when-we-want-it*
> capability, not a new default.

Wiring is in place as of 2026-05-12 and per-runtime routing landed with
issue #66: `celery[redis]>=5.4` is in `packages/core/pyproject.toml`,
`packages/worker/src/ai_platform/entrypoints/celery_app.py` defines the
`run_job` task and scopes the pool to `WORKER_RUNTIME`, and
`CeleryComputeBackend.enqueue` routes `run_job` to the job's runtime
queue. The compose `celery` profile adds `redis`, `celery-worker`, and
`celery-worker-crewai`.

As of #65 it's a clean local **mode**, not a manual juggle: the poll
`worker` lives behind the `poll` profile and `scripts/compose-celery.sh`
pins `COMPOSE_PROFILES=celery` + `COMPUTE=celery`, so the poll loop and
the broker consumer can never both run (no race). A committed test —
`tests/integration/test_celery_broker.py`, run via `scripts/test-celery.sh`
— submits a job and asserts it reaches `SUCCEEDED` through
submit → enqueue → redis → celery-worker, with no poll worker running.
It goes red the moment that chain breaks. Domain-specific environmental
requirements (a domain that calls back into its UI for a validate-* tool,
etc.) are orthogonal to the celery wiring and apply equally to the poll
worker.

### Local: run the celery stack with one command

```bash
# First run only: build the worker image (both consumers use it).
docker compose --profile build build aiplatform-worker

# Bring up api + redis + BOTH per-runtime celery consumers
# (celery-worker + celery-worker-crewai). NO poll worker — the wrapper
# pins COMPOSE_PROFILES=celery so `worker`/`worker-crewai` stay down.
scripts/compose-celery.sh up -d

# Confirm: redis + celery-worker + celery-worker-crewai (+ api), and no
# worker/worker-crewai.
scripts/compose-celery.sh ps
scripts/compose-celery.sh logs -f celery-worker celery-worker-crewai

# Tear down.
scripts/compose-celery.sh down
```

Back to the default poll stack is just `docker compose up -d` (with
`COMPOSE_PROFILES=poll` from `.env`). Validate the broker path any time
with `scripts/test-celery.sh` (spins up a throwaway redis, runs the
committed round-trip test, tears it down).

### Compose additions

These services already live in `docker-compose.yml` (under the `celery`
profile) and `docker-compose.prod.yml` (image pins) — the block below is
the annotated reference; the committed compose is the source of truth.

```yaml
# docker-compose.yml — already present (celery profile).
services:
  redis:
    image: redis:7-alpine
    # AOF on so queued jobs survive a redis restart. fsync-every-sec
    # is the sane default: durability lag bounded to ~1s, no I/O storm.
    command: >
      redis-server
      --appendonly yes
      --appendfsync everysec
    volumes:
      - redis-data:/data
    restart: unless-stopped
    profiles: [celery]

  # One celery consumer PER RUNTIME (the canonical, full definitions live
  # in the repo's docker-compose.yml — this is the shape). Each is the
  # virgin aiplatform-worker image; WORKER_RUNTIME scopes both the domains
  # it registers and the queue it consumes (`runtime.<WORKER_RUNTIME>`).
  celery-worker:                 # WORKER_RUNTIME=default → runtime.default
    image: aiplatform-worker:local
    command: >
      celery -A ai_platform.entrypoints.celery_app worker
      --loglevel=info
      --concurrency=${CELERY_CONCURRENCY:-2}
    environment:
      WORKER_RUNTIME: default
      # Same backend + secrets as `api` / `worker`. Source from .env.
      BACKEND: ${BACKEND:-supabase}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      SUPABASE_URL: ${SUPABASE_URL:-}
      SUPABASE_SECRET_KEY: ${SUPABASE_SECRET_KEY:-}
      SUPABASE_BUCKET: ${SUPABASE_BUCKET:-app-data}
      SUPABASE_CONNECTION_STRING: ${SUPABASE_CONNECTION_STRING:-}
      CELERY_BROKER_URL: redis://redis:6379/0
    depends_on:
      # Wait for the broker to pass its healthcheck (redis-cli ping)
      # before the consumer boots — see `redis.healthcheck` in the
      # actual docker-compose.yml, which is the source of truth.
      redis: { condition: service_healthy }
    restart: unless-stopped
    profiles: [celery]

  celery-worker-crewai:          # WORKER_RUNTIME=crewai → runtime.crewai
    image: aiplatform-worker:local
    command: >
      celery -A ai_platform.entrypoints.celery_app worker
      --loglevel=info
      --concurrency=${CELERY_CONCURRENCY:-2}
    environment:
      WORKER_RUNTIME: crewai     # no LOGFIRE_TOKEN: crewai can't load Logfire
      BACKEND: ${BACKEND:-supabase}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      SUPABASE_URL: ${SUPABASE_URL:-}
      SUPABASE_SECRET_KEY: ${SUPABASE_SECRET_KEY:-}
      SUPABASE_BUCKET: ${SUPABASE_BUCKET:-app-data}
      SUPABASE_CONNECTION_STRING: ${SUPABASE_CONNECTION_STRING:-}
      CELERY_BROKER_URL: redis://redis:6379/0
    depends_on:
      redis: { condition: service_started }
    restart: unless-stopped
    profiles: [celery]

  # Existing `api` gets two extra env vars when running under the
  # celery profile. Easiest: add them unconditionally — they're no-ops
  # when COMPUTE != celery.
  api:
    environment:
      COMPUTE: ${COMPUTE:-poll}
      CELERY_BROKER_URL: redis://redis:6379/0

volumes:
  redis-data:
```

The poll `worker`/`worker-crewai` sit behind the `poll`/`crewai`
profiles and the broker pair + both per-runtime consumers behind
`celery`, so the modes are selected by profile — a fresh bring-up of
one never includes the other. Flipping a box that's *already* running
the poll workers is the **rehearsed, reversible** procedure below —
validated on `mathapp-prod` 2026-06-29 (PASS; timings + evidence under
[§6 Status](#status)).

#### Flip: poll → celery

Add the celery toggles to the box `.env`. `COMPUTE=celery` is the only
*behavioural* change; the broker/concurrency/reaper vars are harmless
no-ops under poll, so it's fine for them to already be present:

```bash
# /srv/mathapp/.env on the box:
COMPUTE=celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_CONCURRENCY=2            # prefork children per consumer; bump to taste
WORKER_JOB_LEASE_TTL_S=900      # reaper TTL; also honoured by the celery beat sweep
```

```bash
# 1. Roll the stack onto the celery profile: redis + BOTH per-runtime
#    consumers (celery-worker [default] + celery-worker-crewai [crewai]),
#    and NOT the poll workers. redeploy.sh maps PROFILES → --profile flags
#    and pulls the GHCR images (no build on the box).
PROFILES="ui celery" infra/hetzner/scripts/redeploy.sh

# 2. CAVEAT — stop the poll workers explicitly. The previous deploy started
#    them (default PROFILES is "ui crewai poll"), and a reduced-profile `up`
#    LEAVES THEM RUNNING: compose never stops a service just because its
#    profile dropped out of this invocation. Both runtimes' poll loops must
#    be down so neither races a consumer for the same job. (`stop`, not
#    `rm` — rollback restarts these same containers.)
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  stop worker worker-crewai
```

After the flip: `api` reports `compute=celery`; redis is up (`appendonly
yes`, no `ports:` mapping → reachable only inside the compose network, and
the Hetzner FW blocks 6379 regardless); and jobs **route by runtime** — a
`math_qa` / `math_notes` submit lands on `celery-worker`, a
`math_conversation` submit on `celery-worker-crewai`, picked up sub-second.
(2026-06-29 rehearsal: ~1.8 s default / ~1.2 s crewai submit→pickup; the
default consumer never touched the crewai job.)

#### Rollback: celery → poll

Drop the one behavioural toggle and redeploy on the default profiles. Keep
the broker/concurrency/reaper vars — they're no-ops once `COMPUTE` is back
to poll, and keeping them makes the next flip a one-line edit:

```bash
# 1. Remove (or comment out) COMPUTE=celery in /srv/mathapp/.env. Leave
#    CELERY_BROKER_URL / CELERY_CONCURRENCY / WORKER_JOB_LEASE_TTL_S in place.

# 2. Redeploy on the default profiles ("ui crewai poll") to bring BOTH poll
#    workers back (this `up -d` restarts the containers `stop`ped above):
infra/hetzner/scripts/redeploy.sh

# 3. Force-remove the celery services — the two per-runtime consumers and
#    redis. They're not in the poll profile set, so the redeploy above won't
#    touch them; remove them so nothing celery is left running.
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  rm -fs celery-worker celery-worker-crewai redis
```

The repo is the durable store either way; both backends see the same
Supabase rows, so no job is lost across a flip or a rollback. (2026-06-29
rollback was clean: `api` back to `compute=poll`, poll workers reconnected,
no stray celery/redis containers, queue quiescent.)

### Operational notes

- **Redis durability.** AOF (`appendonly yes`) means redis can be
  killed and restarted without losing the in-flight queue. Without
  it, a redis restart silently drops queued jobs. Don't skip the
  flag.
- **Memory.** Redis with a handful of small JSON tasks barely
  registers — kilobytes. CX22's 4 GB is plenty.
- **Concurrency.** `--concurrency=2` means two prefork workers
  inside the one container. For domain jobs that mostly wait on an
  upstream LLM, you can push this higher (4–8) before CPU matters.
- **Scaling beyond one box.** Move redis to its own host (or
  Supabase Redis when that lands) and bump `replicas` on
  `celery-worker`. The API side doesn't change.
- **Flower / monitoring.** Add a third service:
  ```yaml
  flower:
    image: mher/flower:2.0
    command: celery --broker=redis://redis:6379/0 flower --port=5555
    profiles: [celery]
  ```
  Reach it at `http://<tailnet-ip>:5555`. No public exposure needed.

### What not to do

- **Don't put redis on a public port.** Even on the same box. With
  no `ports:` mapping, redis is only reachable from inside the
  compose network. Hetzner Cloud Firewall would block 6379 from the
  internet anyway, but the compose default is the right belt.
- **Don't use the same Redis instance as a results backend.** We
  don't need Celery's results backend; `JobRecord.state` in Postgres
  *is* the result store. Setting `result_backend` makes
  `task.delay()` write twice for no benefit.
- **Don't bump worker concurrency past the Supabase connection-pool
  ceiling.** Each celery worker process opens its own `psycopg`
  pool (default `max_size=4`). If you run `--concurrency=8`, that's
  eight pools × four connections = 32 sockets to Postgres from one
  container. Fine on Supabase's session pooler limits today; worth
  knowing when it isn't.
- **Don't bootstrap the workspace at celery_app module load.** Celery's
  prefork pool forks worker children from the master; psycopg
  connections opened in the master are inherited as live FDs that
  the children can't safely use, and the first task on each child
  hangs on `pool.getconn` until `PoolTimeout` (30s). `celery_app.py`
  bootstraps inside `worker_process_init` so each child gets its own
  pool — keep it that way.

---

## Day-2 operations

### Deploying a new version

After `git push origin main`, the GHA workflow builds and publishes a
new image (~1–2 min with the buildx layer cache). Then:

```bash
ssh root@mathapp-prod 'cd /srv/mathapp && git pull && infra/hetzner/scripts/redeploy.sh'
ssh root@mathapp-prod 'cd /srv/mathapp && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=50'
```

`git pull` only refreshes the compose files + scripts on the box —
the actual app code arrives via the `docker compose pull` inside
`redeploy.sh`. To pin a specific build (e.g. a known-good SHA after a
bad `:latest` push):

```bash
ssh root@mathapp-prod 'cd /srv/mathapp && IMAGE_TAG=sha-62d3672 infra/hetzner/scripts/redeploy.sh'
```

### Refresh the SDK snapshot from prod (post-deploy)

After any deploy that changed the API surface (new routes / response
models) **or** a domain's artifact / input / result types, refresh the
committed OpenAPI snapshot **from prod** as the guarantee that the typed
`@sepoul-packages/sdk` contract matches what consumers (`platform-ui` here,
`math-app/math-ui`) actually call. The snapshot is the *source* the SDK
types are generated from — a regen taken against a local/dev instance
only reflects whatever domains + versions happen to be installed there,
so prod is the authoritative dump.

```bash
# From the laptop (on the tailnet), against the just-deployed box:
aiplatform snapshot-openapi --api-url http://mathapp-prod:8000
git commit -am "chore(sdk): refresh openapi snapshot from prod" && git push
```

The push touches `sdk-ts/openapi.snapshot.json`, which triggers
`.github/workflows/sdk-regen.yml`: it guards against a partial
(`_demo`-only) snapshot, regenerates `sdk-ts/src/schema.d.ts`, and
**opens a PR** with the diff. Review + merge it so the typed contract is
authoritative. No diff → no PR (the snapshot was already current).

### Tailing logs

```bash
docker compose logs -f --tail=200 api
docker compose logs -f --tail=200 worker
```

Or from the laptop, the live SSE log stream per job:
`http://<box-tailnet-ip>:8000/jobs/<id>/logs/stream` — same wiring as
[live_logs.md](../guides/live-logs.md).

### Re-running Supabase migrations on the box

If you add a `0002_*.sql`:

```bash
cd /srv/mathapp
git pull
docker compose exec api python -m scripts.supabase_migrate
```

The runner is idempotent.

### Recovering a wedged worker / orphaned RUNNING job

**Symptom.** The `default` poll worker goes silent — last log line is a
job claim (`Claimed job …` / `fresh start at …`), then nothing for a long
time. The container still shows `Up`/healthy. Because the poll worker is
single-threaded (`COMPUTE=poll`, concurrency 1), the one wedged job freezes
the whole queue: jobs submitted afterwards sit `PENDING`, never claimed.

The classic cause (issue #62) is a **stale Supabase pooler connection**:
Supabase rotates its session-pooler endpoint
(`aws-0-eu-west-1.pooler.supabase.com:5432`) during an idle window, the
peer never sends RST/FIN, and the worker's next DB read blocks forever on a
half-open socket.

**Diagnose** (over the tailnet, `ssh root@mathapp-prod`, in `/srv/mathapp`):

```bash
# Last worker log line is the job claim, nothing after:
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=50 worker

# Main thread parked in a no-timeout socket read (do_poll):
docker compose exec worker sh -c 'cat /proc/1/task/1/wchan; echo'

# The tell: the worker clings to ONE ESTABLISHED conn to a pooler IP that
# DNS no longer returns (the rotated-away endpoint).
docker compose exec worker sh -c \
  'ss -tnp 2>/dev/null | grep :5432; echo "--- DNS now:"; getent hosts aws-0-eu-west-1.pooler.supabase.com'
```

If the connected `:5432` IP differs from what `getent hosts` resolves, the
worker is on a dead socket.

**Recover** (manual):

```bash
# 1. Mark the stuck job(s) terminal. The API only updates the DB row — it
#    does NOT unstick the wedged worker process.
curl -fsS -X POST http://mathapp-prod:8000/jobs/<id>/cancel   # or: aip cancel <id>

# 2. Restart the worker with a SHORT stop grace. Its SIGTERM handler
#    ("finish current job then exit") would itself hang on the dead job, so
#    don't wait out the default 10s twice.
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart -t 5 worker
```

Verify: the worker reboots, reconnects to the live pooler IP, and returns
to clean polling (`No pending jobs, sleeping …`) with 0 active jobs.

**Durable mitigations now in place** (so this should self-heal — issue #62):

- **DB-socket fail-fast.** `make_pool`
  (`packages/core/src/ai_platform/workspace/storage/structured/supabase.py`)
  sets TCP keepalives **plus** `tcp_user_timeout=30s` and a `statement_timeout`,
  so a dead pooler connection now errors in ~30s instead of hanging — the
  worker loop catches it, marks the job FAILED-retryable, and keeps polling.
  All consumers (api, both workers, celery) inherit this through the one
  central pool factory.
- **Lease reaper.** Set `WORKER_JOB_LEASE_TTL_S` (seconds) in `.env`. A
  RUNNING job whose worker stopped heartbeating for longer than the TTL is
  reclaimed: released back to `PENDING` for re-claim, or marked `FAILED`
  once `max_attempts` is used. The poll worker reaps on boot and on every
  idle tick, so a job orphaned by a crashed/restarted worker no longer sits
  `RUNNING` forever. Pick a TTL comfortably larger than the longest gap
  between a healthy job's progress updates (e.g. `900`) to avoid reclaiming
  a slow-but-live job.

---

## What's NOT addressed yet

Tracking these here rather than spreading them across the doc.

- **TLS / public exposure.** Only relevant for Path B (Vercel UI) or
  if you want to share a job-result URL with a non-tailnet device.
  Caddy in front of compose, `https://<your.domain>` → `api:8000`.
- **Auth on the API.** Today there's none, because reachability is
  the auth. When Path B becomes relevant, this becomes load-bearing.
- **Backups for non-Supabase backends.** `BACKEND=local` on the box
  with a docker volume means you'd want regular snapshots of
  `mathapp-data`. With `BACKEND=supabase`, Supabase handles
  Postgres + Storage backups already; the box itself is stateless.
- **Observability beyond `docker compose logs`.** Logfire is wired
  but no dashboards/alerting are set up on the deployed box.
- **Secrets rotation.** `.env` lives on the box filesystem. When you
  rotate `SUPABASE_SECRET_KEY` or the DB password, you re-`scp` the
  file and `docker compose up -d`.

---

## Reference: the env-shape on the box

The compose file now passes Supabase vars through identically to the
B2 ones. Same `.env.example`:

```
BACKEND=supabase
ANTHROPIC_API_KEY=…
LOGFIRE_TOKEN=…
WORKER_INTERVAL=5
WORKER_JOB_LEASE_TTL_S=900     # reclaim a RUNNING job orphaned by a dead worker

SUPABASE_SCHEMA=public        # explicit; PROD owns the live `public` tables
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=sb_secret_…
SUPABASE_BUCKET=app-data
SUPABASE_CONNECTION_STRING=postgresql://…
```

Maintained locally as `.prodenv` (gitignored) and scp'd to the box as
`.env` — see Step 4 and `.prodenv.example`.

See [storage_backends.md](../reference/storage-backends.md) for which vars each
backend needs.
