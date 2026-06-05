#!/usr/bin/env bash
# Regenerate the SDK's typed API contract from the platform's OpenAPI
# schema. The generated types are committed to the SDK so consumers
# (math-ui, platform-ui, friend repos) get them transitively via
# `npm install @aiplatform/sdk` — no per-consumer codegen needed.
#
# Same source-resolution ladder as math-ui/scripts/gen-api.sh:
#   1. $OPENAPI_SOURCE   — file path or http(s) URL
#   2. $MATHAPP_REPO     — path to a mathapp checkout
#   3. ..                — monorepo parent
#   4. http://127.0.0.1:8000/openapi.json — fallback
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

OUT="src/schema.d.ts"
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
  echo "[gen-api] source: $url (fallback)" >&2
  curl -sfSL "$url" -o "$TMP"
}

resolve_source
mkdir -p "$(dirname "$OUT")"
npx --yes openapi-typescript "$TMP" \
  --output "$OUT" \
  --default-non-nullable \
  --root-types

echo "[gen-api] wrote $OUT"
