#!/usr/bin/env bash
# Regenerate the typed API contract from the FastAPI OpenAPI schema.
#
# Source resolution (first match wins):
#   1. $OPENAPI_SOURCE   — file path or http(s) URL
#   2. $MATHAPP_REPO     — path to a mathapp checkout; runs its dump script
#   3. ..                — monorepo parent (mathapp root), runs its dump script
#   4. http://127.0.0.1:8000/openapi.json — fall back to a running api.sh
#
# Output: lib/api/schema.d.ts (committed; PR diffs surface contract drift).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

OUT="lib/api/schema.d.ts"
TMP="$(mktemp -t openapi.XXXXXX.json)"
trap 'rm -f "$TMP"' EXIT

resolve_source() {
  if [[ -n "${OPENAPI_SOURCE:-}" ]]; then
    echo "[gen-api] source: \$OPENAPI_SOURCE=$OPENAPI_SOURCE" >&2
    if [[ "$OPENAPI_SOURCE" =~ ^https?:// ]]; then
      curl -sfSL "$OPENAPI_SOURCE" -o "$TMP"
    else
      cp "$OPENAPI_SOURCE" "$TMP"
    fi
    return
  fi

  local mathapp="${MATHAPP_REPO:-}"
  if [[ -z "$mathapp" && -x "$REPO_ROOT/../scripts/dump-openapi.sh" ]]; then
    mathapp="$(cd "$REPO_ROOT/.." && pwd)"
  fi
  if [[ -n "$mathapp" && -x "$mathapp/scripts/dump-openapi.sh" ]]; then
    echo "[gen-api] source: $mathapp/scripts/dump-openapi.sh" >&2
    "$mathapp/scripts/dump-openapi.sh" "$TMP"
    return
  fi

  local url="http://127.0.0.1:8000/openapi.json"
  echo "[gen-api] source: $url (fallback — start mathapp's scripts/api.sh)" >&2
  curl -sfSL "$url" -o "$TMP"
}

resolve_source
mkdir -p "$(dirname "$OUT")"
npx --yes openapi-typescript "$TMP" \
  --output "$OUT" \
  --default-non-nullable \
  --root-types

echo "[gen-api] wrote $OUT"
