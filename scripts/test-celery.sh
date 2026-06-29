#!/usr/bin/env bash
# Run the committed Celery broker round-trip test (issue #65).
#
# Proves submit → enqueue → redis → celery-worker → SUCCEEDED end to end.
# The test (tests/integration/test_celery_broker.py) spawns its own celery
# worker and skips unless a redis broker is reachable, so this wrapper's
# only job is to make sure one IS reachable: it spins up a throwaway redis
# container, points CELERY_BROKER_URL at it, runs the test, and tears it
# down again.
#
# Usage:
#   scripts/test-celery.sh                 # throwaway redis on :6399, run the test
#   CELERY_BROKER_URL=redis://host:6379/0 scripts/test-celery.sh   # reuse an existing broker
#   scripts/test-celery.sh -v -s           # extra args forwarded to pytest
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

TEST=tests/integration/test_celery_broker.py

# If the caller already has a broker, just use it — don't touch docker.
if [[ -n "${CELERY_BROKER_URL:-}" ]]; then
  echo "[test-celery] using existing CELERY_BROKER_URL=$CELERY_BROKER_URL"
  exec "$PY" -m pytest "$TEST" "$@"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[test-celery] error: docker not found and CELERY_BROKER_URL unset —" >&2
  echo "[test-celery] start a redis and export CELERY_BROKER_URL, or install docker." >&2
  exit 1
fi

REDIS_NAME="aiplatform-test-redis"
REDIS_PORT="${REDIS_PORT:-6399}"
export CELERY_BROKER_URL="redis://localhost:${REDIS_PORT}/0"

cleanup() { docker rm -f "$REDIS_NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "[test-celery] starting throwaway redis ($REDIS_NAME) on :$REDIS_PORT"
docker rm -f "$REDIS_NAME" >/dev/null 2>&1 || true
docker run -d --name "$REDIS_NAME" -p "${REDIS_PORT}:6379" redis:7-alpine >/dev/null

# Wait for the broker to accept connections before handing off to pytest.
for _ in $(seq 1 30); do
  if docker exec "$REDIS_NAME" redis-cli ping 2>/dev/null | grep -q PONG; then
    break
  fi
  sleep 0.5
done

"$PY" -m pytest "$TEST" "$@"
