#!/usr/bin/env bash
# Pull the latest mathapp + math-ui images from GHCR and roll the stack.
#
# Runs on the Hetzner box. Assumes this repo is checked out and that
# docker + docker-compose-v2 are installed (cloud-init handles both).
#
# Usage:
#   ./redeploy.sh                         # api + worker + math-ui, :latest
#   IMAGE_TAG=sha-abc1234 ./redeploy.sh   # pin to a specific build
#   PROFILES= ./redeploy.sh               # api + worker only (skip the UI)
#   PROFILES="ui celery" ./redeploy.sh    # swap in extra profiles

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

PROFILES="${PROFILES-ui}"
PROFILE_FLAGS=()
for p in $PROFILES; do
  PROFILE_FLAGS+=(--profile "$p")
done

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml "${PROFILE_FLAGS[@]}")

"${COMPOSE[@]}" pull
"${COMPOSE[@]}" up -d
docker image prune -f
