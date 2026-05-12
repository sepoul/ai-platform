#!/usr/bin/env bash
# Dump the FastAPI app's OpenAPI schema to stdout (or to $1 if given).
#
# Offline export — imports the app directly, no server, no port. The
# generated schema is the single source of truth for the math-ui
# TypeScript codegen pipeline (see math-ui/scripts/gen-api.sh).
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

OUT="${1:-/dev/stdout}"

"$PY" -c "
import json, sys
from mathapp.entrypoints.api import app
sys.stdout.write(json.dumps(app.openapi(), indent=2))
" > "$OUT"
