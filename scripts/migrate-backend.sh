#!/usr/bin/env bash
# Copy every entity (jobs / artifacts / prompts / prompt_executions / files)
# from one storage backend to another. Idempotent — safe to re-run.
#
# Examples:
#   ./scripts/migrate-backend.sh --source local --target supabase
#   ./scripts/migrate-backend.sh --source local --target supabase --dry-run
#   ./scripts/migrate-backend.sh --source supabase --target local --what jobs,artifacts
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

exec "$PY" -u -m scripts.migrate_backend "$@"
