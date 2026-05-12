#!/usr/bin/env bash
# Idempotently deploy v0 prompt definitions to the configured backend.
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

ARGS=(--backend "$BACKEND")
if [[ "$BACKEND" == "local" && -n "${LOCAL_DATA_DIR:-}" ]]; then
  ARGS+=(--data-dir "$LOCAL_DATA_DIR")
fi

echo "[deploy-prompts] backend=$BACKEND data=${LOCAL_DATA_DIR:-<default>}"
exec "$PY" -u -m scripts.deploy_prompts "${ARGS[@]}" "$@"
