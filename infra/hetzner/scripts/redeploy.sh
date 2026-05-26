#!/usr/bin/env bash
# Pull the latest mathapp images (api + both worker runtimes) and math-ui
# from GHCR and roll the stack.
#
# Runs on the Hetzner box. Assumes this repo is checked out and that
# docker + docker-compose-v2 are installed (cloud-init handles both).
#
# Production runs BOTH worker runtimes simultaneously — `worker` for
# default-runtime domains (math_qa, pydantic_ai) and `worker-crewai` for
# the CrewAI runtime (math_conversation). They are NOT swappable (unlike
# storage / compute backends); each domain is assigned to a runtime and
# both serve in parallel.
#
# Usage:
#   ./redeploy.sh                         # api + both workers + math-ui (default)
#   IMAGE_TAG=sha-abc1234 ./redeploy.sh   # pin to a specific build
#   PROFILES= ./redeploy.sh               # api + default worker only (no crewai, no UI)
#   PROFILES="ui crewai celery" ./redeploy.sh   # also bring up celery-worker

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

PROFILES="${PROFILES-ui crewai}"
PROFILE_FLAGS=()
for p in $PROFILES; do
  PROFILE_FLAGS+=(--profile "$p")
done

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml "${PROFILE_FLAGS[@]}")

"${COMPOSE[@]}" pull
"${COMPOSE[@]}" up -d
docker image prune -f
