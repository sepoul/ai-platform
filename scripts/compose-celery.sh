#!/usr/bin/env bash
# One-command local Celery stack: api + redis + both per-runtime celery
# consumers (celery-worker for `default`, celery-worker-crewai for
# `crewai`; issue #66), with NO poll worker running (so the poll loops
# can't race the broker consumers).
#
# It pins two things the celery mode needs and that a stale `.env` could
# otherwise get wrong:
#   COMPOSE_PROFILES=celery  → only the `celery` profile is active. The
#       poll `worker`/`worker-crewai` live behind `poll`/`crewai`, so they
#       stay down. A shell value overrides `.env`, and the CLI/ shell
#       profile set *replaces* (not merges) COMPOSE_PROFILES — so even an
#       `.env` that says `COMPOSE_PROFILES=poll` can't leak the poll worker
#       back in.
#   COMPUTE=celery           → the API enqueues to redis instead of leaving
#       jobs for a poll loop that isn't running.
#
# Everything after the script name is forwarded to `docker compose`:
#   scripts/compose-celery.sh up -d        # bring the stack up
#   scripts/compose-celery.sh ps           # redis + both consumers (+ api)
#   scripts/compose-celery.sh logs -f celery-worker celery-worker-crewai
#   scripts/compose-celery.sh down         # tear it down
#
# First run needs the worker image built (same as poll mode):
#   docker compose --profile build build aiplatform-worker
#
# See docs/operations/hetzner-deploy.md §6.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export COMPOSE_PROFILES=celery
export COMPUTE=celery

exec docker compose "$@"
