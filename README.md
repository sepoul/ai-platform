# mathapp

FastAPI + worker for math-AI jobs.

## Run locally

Docker Compose is the only supported run path right now — there is no
production deployment story yet.

```bash
cp .env.example .env       # set ANTHROPIC_API_KEY
docker compose up --build  # first run, or after dep changes
docker compose up          # subsequent runs
```

This brings up two services:

- **api** — FastAPI on `http://localhost:8000` (health: `/health`,
  OpenAPI: `/docs`). Reach it from a Next.js dev server on the host.
- **worker** — polls the shared volume for pending jobs.

Both share a named docker volume (`mathapp-data`) mounted at `/data`,
which is `LOCAL_DATA_DIR` — the local-backend job repo + artifact store.

Tail logs / restart one service:

```bash
docker compose logs -f worker
docker compose restart api
```

Three storage backends are available:

- `BACKEND=local` (default) — JSON on disk
- `BACKEND=b2` — Backblaze (`B2_KEY_ID`, `B2_APP_KEY`, `B2_BUCKET`)
- `BACKEND=supabase` — Postgres + Supabase Storage (`SUPABASE_URL`,
  `SUPABASE_SECRET_KEY`, `SUPABASE_CONNECTION_STRING`,
  `SUPABASE_BUCKET`)

Full breakdown: [`docs/storage_backends.md`](docs/storage_backends.md).

### Pluggable compute

Storage isn't the only swappable layer. `COMPUTE` selects how a
submitted job reaches a worker:

| `COMPUTE` | Worker | Use when |
|---|---|---|
| `poll` (default) | separate `scripts/worker.sh` | what compose runs |
| `thread` | none — runs in the API process | single-process dev |
| `celery` | `celery -A …` (stub) | future, with a broker |

```bash
COMPUTE=thread BACKEND=local ./scripts/api.sh
# submit a job — runs in-process, no worker.sh needed
```

Full breakdown + the Celery migration plan: [docs/compute_backends.md](docs/compute_backends.md).

## Run on the host (Unix)

For iterating on a single service without docker, use the bash entry
points in [`scripts/`](scripts/). They auto-pick the project venv
(`./.venv` first), load `.env`, and default `BACKEND=local` with
`LOCAL_DATA_DIR=./mathdata`.

```bash
./scripts/dev.sh                     # api + worker, one terminal, tagged logs
./scripts/api.sh                     # uvicorn on 127.0.0.1:8000
./scripts/api.sh --reload            # extra args go through to uvicorn
PORT=9000 ./scripts/api.sh           # override via env
./scripts/worker.sh                  # poll loop
./scripts/worker.sh --once           # one job then exit
./scripts/deploy-prompts.sh          # idempotent prompt seeding
./scripts/test.sh                    # pytest, args forwarded
```

`scripts/_lib.sh` is the shared bootstrap (sourced, not executed).

## Tests

```bash
./scripts/test.sh
```
