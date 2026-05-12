#!/usr/bin/env bash
# Live-reloading docs server. Defaults to 127.0.0.1:8001 because
# 8000 is the FastAPI port — running both side by side is the
# common case.
#
# Knobs (env or CLI):
#   PORT     — default 8001
#   HOST     — default 127.0.0.1
#
# Extra args go straight to `mkdocs serve` (e.g. --strict, --watch).
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8001}"

# A plugin we depend on prints a marketing notice on every build
# pointing at a fork. Silenced as suggested by the upstream warning.
export DISABLE_MKDOCS_2_WARNING=true

echo "docs → http://$HOST:$PORT"
exec "$PY" -m mkdocs serve --dev-addr "$HOST:$PORT" "$@"
