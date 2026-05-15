#!/usr/bin/env bash
# Pull the latest mathapp image from GHCR and roll the stack.
#
# Runs on the Hetzner box. Assumes this repo is checked out and that
# docker + docker-compose-v2 are installed (cloud-init handles both).
#
# Usage:
#   ./redeploy.sh                         # uses :latest
#   IMAGE_TAG=sha-abc1234 ./redeploy.sh   # pin to a specific build

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)

"${COMPOSE[@]}" pull
"${COMPOSE[@]}" up -d
docker image prune -f
