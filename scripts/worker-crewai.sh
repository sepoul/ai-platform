#!/usr/bin/env bash
# Start the crewai-runtime worker on the host. Mirrors worker.sh but
# binds to .venv-crewai (slim crewai stack — mutually exclusive with
# the default runtime's logfire+otel-sdk pin, so one venv per runtime
# is the only way to run both on the host) and runs as
# WORKER_RUNTIME=crewai so it only claims math_conversation jobs.
#
# Knobs (env or .env): WORKER_INTERVAL  BACKEND  ANTHROPIC_API_KEY
# Extra args are forwarded to the worker (e.g. --once).
#
# First-time setup:
#   uv venv .venv-crewai --python 3.13
#   VIRTUAL_ENV="$PWD/.venv-crewai" uv pip install -e "packages/worker[crewai]"
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

# Override the python that _lib.sh picked. _lib's default points at .venv
# (the default-runtime stack); we need the crewai venv here.
PY="$REPO_ROOT/.venv-crewai/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "[worker-crewai] .venv-crewai not found at $PY" >&2
  echo "[worker-crewai] create it with:" >&2
  echo "    uv venv .venv-crewai --python 3.13" >&2
  echo "    VIRTUAL_ENV=\"\$PWD/.venv-crewai\" uv pip install -e \"packages/worker[crewai]\"" >&2
  exit 1
fi

export WORKER_RUNTIME=crewai
INTERVAL="${WORKER_INTERVAL:-5}"
MAX_AGE="${WORKER_MAX_JOB_AGE_S:-}"

echo "backend=$BACKEND runtime=crewai interval=${INTERVAL}s max_job_age=${MAX_AGE:-unlimited}"
exec "$PY" -u -m ai_platform.entrypoints.worker --interval "$INTERVAL" "$@"
