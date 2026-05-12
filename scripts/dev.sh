#!/usr/bin/env bash
# Start api + worker on the host with one command, multiplexing their logs.
#
# Each line is tagged so you can grep one stream:
#   scripts/dev.sh | grep '^\[worker\]'
#
# Ctrl-C tears both down. If either exits (e.g. uvicorn crashes), the
# other is taken down with it so you don't end up with a half-running stack.
#
# Knobs propagate to the child scripts via env / .env (HOST, PORT, BACKEND,
# WORKER_INTERVAL, …). This script intentionally takes no flags — for
# tweaks, run scripts/api.sh or scripts/worker.sh directly.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Pull HOST/PORT from .env so the port check matches what api.sh will use.
REPO_ROOT="$(cd "$HERE/.." && pwd)"
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

# Fail loudly if an old api is still bound — uvicorn's own error gets buried
# in interleaved logs and the leftover keeps writing to the parent terminal.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[dev] port $PORT is already in use:" >&2
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2
  echo "[dev] kill it (e.g. 'kill \$(lsof -ti:$PORT)') or run with PORT=…" >&2
  exit 1
fi

if [[ -t 1 ]]; then
  API_TAG=$'\033[36m[api]   \033[0m'
  WRK_TAG=$'\033[35m[worker]\033[0m'
else
  API_TAG='[api]   '
  WRK_TAG='[worker]'
fi

# Process substitution keeps $! pointing at the child script (which
# `exec`s its server), so we can signal it directly. awk handles the
# per-line prefixing; fflush() keeps logs live with no buffering.
"$HERE/api.sh"    > >(awk -v t="$API_TAG" '{ print t, $0; fflush() }') 2>&1 &
api_pid=$!
"$HERE/worker.sh" > >(awk -v t="$WRK_TAG" '{ print t, $0; fflush() }') 2>&1 &
worker_pid=$!

cleanup() {
  trap - INT TERM EXIT
  kill -TERM "$api_pid" "$worker_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# Poll instead of `wait -n` so this works with macOS-default bash 3.2.
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$worker_pid" 2>/dev/null; do
  sleep 0.5
done

# Surface the first-to-die's exit status; the EXIT trap kills the other.
if ! kill -0 "$api_pid" 2>/dev/null; then
  wait "$api_pid"
else
  wait "$worker_pid"
fi
