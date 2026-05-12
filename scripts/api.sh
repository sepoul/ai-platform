#!/usr/bin/env bash
# Start the FastAPI server on the host. Defaults: 127.0.0.1:8000, local backend.
#
# Knobs (env or .env):  HOST  PORT  BACKEND  LOCAL_DATA_DIR  ANTHROPIC_API_KEY
# Extra args are forwarded to uvicorn (e.g. --reload, --log-level debug).
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

echo "backend=$BACKEND data=${LOCAL_DATA_DIR:-<default>} → http://$HOST:$PORT"
exec "$PY" -u -m uvicorn mathapp.entrypoints.api:app --host "$HOST" --port "$PORT" "$@"
