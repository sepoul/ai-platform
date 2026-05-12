#!/usr/bin/env bash
# Run the test suite. Extra args are forwarded to pytest.
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

exec "$PY" -m pytest tests "$@"
