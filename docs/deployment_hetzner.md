# Deployment — single Hetzner box

A pragmatic plan for getting the stack onto one Hetzner VM, reachable
only from your laptop, with as little moving infrastructure as the
problem allows. Single-tenant, single-developer. Not a multi-region
zero-downtime story; that's a different document.

> **Status (2026-05-12): step 1 done locally.** The compose stack has
> been smoke-tested on the laptop against Supabase — `BACKEND=supabase
> docker compose up` boots clean, `/health` returns 200, `/jobs` returns
> the expected count, and the poll worker iterates without errors.
> Step 6's Celery wiring is also implemented and locally smoke-tested
> via `--profile celery`. The Hetzner box itself has not been
> provisioned yet — steps 2–4 are still ahead.

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

## Step 2 — Provision the box

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
apt install -y docker.io docker-compose-plugin git
systemctl enable --now docker
```

---

## Step 3 — Lock down with Tailscale + Hetzner Cloud Firewall

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

```bash
# On the box, after docker + tailscale.
cd /srv
git clone https://github.com/<you>/mathapp.git
cd mathapp

# Copy .env from laptop. Don't paste secrets into ssh prompts; use scp:
#   from laptop:  scp .env root@<tailnet-ip>:/srv/mathapp/.env
```

Make sure `.env` on the box has:

- `BACKEND=supabase`
- `ANTHROPIC_API_KEY=…`
- `LOGFIRE_TOKEN=…` (required — `basic_agent.py` calls `logfire.configure()` at import time)
- `SUPABASE_URL=…`
- `SUPABASE_SECRET_KEY=…`
- `SUPABASE_BUCKET=app-data`
- `SUPABASE_CONNECTION_STRING=…`

Boot the stack:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f
```

From the laptop on the tailnet:

```bash
curl -fsS http://<box-tailnet-ip>:8000/health
curl -s   http://<box-tailnet-ip>:8000/jobs | jq length
```

Should match your local dev's view of the cleaned Supabase data.

---

## Step 5 — math-ui

Two paths, depending on how you want to access the UI.

### Path A — co-deploy on the same box (recommended for now)

The Next.js app runs as a third container; it talks to the API at
`http://api:8000` over the docker network (compose service name).
The user reaches `http://<box-tailnet-ip>:3000` from the laptop —
which proxies to the API container internally, so the API still
doesn't need to be reachable from the public.

Out of scope for this commit — needs a small UI service added to
compose with the math-ui repo checked out next to mathapp. Sketched
as future work below.

### Path B — Vercel for the UI, public API on the box

Vercel can't reach a tailnet. To make this work the API has to be
publicly reachable, which means:

- Add a real auth layer (JWT, Cloudflare Access, magic-link, …).
- Add TLS — Caddy on the box does this in 5 lines.
- Open port 443 in the firewall.

Bigger lift. Defer until there's a real need for the UI to be
accessible from devices not on the tailnet.

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
`requirements.txt`, `src/mathapp/entrypoints/celery_app.py` defines
the `run_job` task, and `CeleryComputeBackend.enqueue` calls
`run_job.delay(job_id)`. The compose `celery` profile adds `redis`
and `celery-worker`.

Local smoke-tested end-to-end against Supabase: submit → enqueue →
redis → celery-worker → `mark_running` → graph execution. The
math_qa workflow itself depends on math-ui at `_ui_url()` for
`validate-latex`; that's an environmental requirement orthogonal to
the celery wiring and applies equally to the poll worker.

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
    build: { context: ., dockerfile: Dockerfile }
    image: mathapp:local
    command: >
      celery -A mathapp.entrypoints.celery_app worker
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

# Bring up everything, including the new services.
docker compose --profile celery up -d --build

# Stop the old poll worker — its job is now redis + celery-worker's.
docker compose stop worker
docker compose rm -f worker
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
  inside the one container. For a math_qa job that's mostly waiting
  on Anthropic, you can push this higher (4–8) before CPU matters.
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

```bash
ssh root@<box-tailnet-ip>
cd /srv/mathapp
git pull
docker compose up -d --build      # rebuild + recreate changed services
docker compose logs -f --tail=50  # confirm clean boot
```

If you want zero-downtime someday, push images to GHCR and `docker
compose pull && docker compose up -d` — but for single-developer
single-tenant, the rebuild-on-the-box loop is fine.

### Tailing logs

```bash
docker compose logs -f --tail=200 api
docker compose logs -f --tail=200 worker
```

Or from the laptop, the live SSE log stream per job:
`http://<box-tailnet-ip>:8000/jobs/<id>/logs/stream` — same wiring as
[live_logs.md](live_logs.md).

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
- **math-ui co-deployment.** Sketched above (Path A); not yet
  implemented in compose. Needs the math-ui repo on the box and a
  third compose service.
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

SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=sb_secret_…
SUPABASE_BUCKET=app-data
SUPABASE_CONNECTION_STRING=postgresql://…
```

See [storage_backends.md](storage_backends.md) for which vars each
backend needs.
