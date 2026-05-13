#!/usr/bin/env bash
# Print connection cheatsheet for the provisioned Hetzner box.
#
# Reads `tofu output` (falls back to `terraform output`) so the values
# stay in sync with whatever state file is current. Prints:
#   - public IPv4 (bootstrap SSH only)
#   - server name (use this for tailnet SSH once Tailscale is up)
#   - copy-paste commands for the three connection modes
#
# Usage:  ./infra/hetzner/scripts/connect.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE/.."

# Prefer tofu; fall back to terraform — same .tf files work with both.
if command -v tofu >/dev/null 2>&1; then
  TF=tofu
elif command -v terraform >/dev/null 2>&1; then
  TF=terraform
else
  echo "error: neither tofu nor terraform on PATH" >&2
  exit 1
fi

if [[ ! -f terraform.tfstate && ! -f .terraform/terraform.tfstate ]]; then
  echo "error: no state file in $(pwd). Run '$TF apply' first." >&2
  exit 1
fi

server_name="$("$TF" output -raw server_name 2>/dev/null || echo '')"
ipv4="$("$TF" output -raw server_ipv4 2>/dev/null || echo '')"

if [[ -z "$server_name" || -z "$ipv4" ]]; then
  echo "error: tofu output is empty. Run '$TF apply' first." >&2
  exit 1
fi

cat <<EOF
Server:        $server_name
Public IPv4:   $ipv4

Bootstrap SSH (works the moment the box is up; needs your laptop IP
in allowed_ssh_cidrs):

  ssh root@$ipv4

Tailnet SSH (works once the box has finished 'tailscale up'; requires
Tailscale running on your laptop with MagicDNS on):

  ssh root@$server_name
  tailscale ssh root@$server_name      # skip ssh keys entirely

App URLs over the tailnet (after step 4 brings docker compose up):

  http://$server_name:8000/health
  http://$server_name:8000/jobs

Wait for first-boot bootstrap (apt + docker + tailscale install) to
finish:

  ssh root@$ipv4 'cloud-init status --wait'

Tailscale status from the laptop:

  tailscale status | grep $server_name
EOF
