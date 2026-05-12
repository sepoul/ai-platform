#!/usr/bin/env bash
# Start the job-polling worker on the host.
#
# Knobs (env or .env):  WORKER_INTERVAL  BACKEND  LOCAL_DATA_DIR  ANTHROPIC_API_KEY
# Extra args are forwarded to the worker (e.g. --once).
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

INTERVAL="${WORKER_INTERVAL:-5}"

echo "backend=$BACKEND data=${LOCAL_DATA_DIR:-<default>} interval=${INTERVAL}s"
exec "$PY" -u -m mathapp.entrypoints.worker --interval "$INTERVAL" "$@"
