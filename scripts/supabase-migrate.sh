#!/usr/bin/env bash
# Apply Supabase SQL migrations against SUPABASE_CONNECTION_STRING.
# Idempotent — safe to re-run.
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

echo "[supabase-migrate] applying migrations from supabase/migrations/"
exec "$PY" -u -m scripts.supabase_migrate "$@"
