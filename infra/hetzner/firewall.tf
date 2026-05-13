# Hetzner Cloud Firewall — belt to Tailscale's braces. Default-deny
# inbound; only SSH from `allowed_ssh_cidrs` and ICMP from anywhere.
#
# Notice: no rule for port 8000 / 3000. The API is reachable only over
# the tailnet by design. See docs/deployment_hetzner.md step 3.
#
# Egress: Hetzner allows all outbound by default and there's no
# `direction = "out"` rule here, so the box can reach Supabase /
# Anthropic / Tailscale control plane normally.

resource "hcloud_firewall" "mathapp" {
  name = "${var.server_name}-fw"

  # SSH for bootstrap. Empty `allowed_ssh_cidrs` → no public SSH at
  # all; you'd need console access or Tailscale-up via cloud-init to
  # ever reach the box.
  dynamic "rule" {
    for_each = length(var.allowed_ssh_cidrs) > 0 ? [1] : []
    content {
      direction  = "in"
      protocol   = "tcp"
      port       = "22"
      source_ips = var.allowed_ssh_cidrs
    }
  }

  # ICMP for ping/liveness. Cheap, harmless, makes "is the box up?" a
  # one-liner from anywhere.
  rule {
    direction = "in"
    protocol  = "icmp"
    source_ips = [
      "0.0.0.0/0",
      "::/0",
    ]
  }
}
