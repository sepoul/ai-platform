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
> Step 6's Celery wiring is implemented and locally smoke-tested via
> `--profile celery`; not yet exercised on the box. The manual
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
┌──────────────┐                                ┌──────────────────────────┐
│   laptop     │ ── tailnet ─▶                  │   Hetzner CX22           │
│              │                                │                          │
│              │   :8000 ▶  api ─enqueue──────▶ │   redis (broker)         │
│              │                                │     │                    │
│              │                                │     ▼                    │
│              │                                │   celery-worker          │
└──────────────┘                                │     │                    │
                                                │     │ psycopg + httpx    │
                                                │     ▼                    │
                                                │   Supabase eu-west-1     │
                                                └──────────────────────────┘
```

Two new containers next to `api`: `redis` and `celery-worker`. The
existing poll `worker` service goes away (or stays behind a profile
so you can flip back).

### Status

Wiring is in place as of 2026-05-12: `celery[redis]>=5.4` is in
`packages/core/pyproject.toml`, `packages/worker/src/ai_platform/entrypoints/celery_app.py`
defines the `run_job` task, and `CeleryComputeBackend.enqueue` calls
`run_job.delay(job_id)`. The compose `celery` profile adds `redis`
and `celery-worker`.

Local smoke-tested end-to-end against Supabase: submit → enqueue →
redis → celery-worker → `mark_running` → graph execution. Domain-
specific environmental requirements (a domain that calls back into
its UI for a validate-* tool, etc.) are orthogonal to the celery
wiring and apply equally to the poll worker.

### Compose additions

```yaml
# docker-compose.yml — append.
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

  celery-worker:
    build: { context: ., dockerfile: Dockerfile.worker, args: { EXTRA: default } }
    image: aiplatform-worker-mathqa:local
    command: >
      celery -A ai_platform.entrypoints.celery_app worker
      --loglevel=info
      --concurrency=${CELERY_CONCURRENCY:-2}
    environment:
      # Same backend + secrets as `api` / `worker`. Source from .env.
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

The `profiles: [celery]` markers mean `docker compose up -d` alone
keeps using the poll worker (current behavior). When you're ready:

```bash
# .env on the box gets two new lines:
COMPUTE=celery
CELERY_CONCURRENCY=2   # bump to taste

# Bring up everything, including the new services. The override file
# points the celery-worker image at GHCR; no build on the box.
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --profile celery pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --profile celery up -d

# Stop the old poll worker — its job is now redis + celery-worker's.
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop worker
docker compose -f docker-compose.yml -f docker-compose.prod.yml rm -f worker
```

To roll back: unset `COMPUTE`, `docker compose up -d worker`, take
down the celery services. The repo is the durable store either way;
both backends see the same Supabase rows.

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
