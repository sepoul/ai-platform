# shellcheck shell=bash
# Shared bootstrap for scripts/*.sh — sourced, not executed.
#
# Picks a Python interpreter, loads .env, sets PYTHONPATH and sensible
# default backend / data dir so each script can be a one-liner.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Pick a Python: project ./.venv → activated venv → python3 on PATH.
# The in-repo venv wins so scripts work even when an unrelated venv is
# activated in the parent shell.
if [[ -x "./.venv/bin/python" ]]; then
  PY="./.venv/bin/python"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
  PY="$VIRTUAL_ENV/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
  echo "[scripts] no .venv detected, using $PY" >&2
else
  echo "[scripts] error: no python interpreter found" >&2
  exit 1
fi
export PY

# Load .env (auto-export every var). Same file compose uses.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# Defaults.
export PYTHONPATH="${PYTHONPATH:-$REPO_ROOT/src}"
export BACKEND="${BACKEND:-local}"
if [[ "$BACKEND" == "local" && -z "${LOCAL_DATA_DIR:-}" ]]; then
  export LOCAL_DATA_DIR="$REPO_ROOT/mathdata"
fi
