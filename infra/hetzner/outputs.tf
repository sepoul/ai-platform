# What you need to copy-paste after `tofu apply`. Tailnet IP is *not*
# known at apply time — it's assigned by the Tailscale control plane
# after the box runs `tailscale up`. Read it with:
#
#   ssh root@$(tofu output -raw server_ipv4) cat /var/log/tailscale-ip.txt
#
# (only present when tailscale_auth_key was supplied).

output "server_id" {
  description = "Hetzner server ID — useful for hcloud CLI."
  value       = hcloud_server.mathapp.id
}

output "server_name" {
  description = "Hostname / Hetzner display name."
  value       = hcloud_server.mathapp.name
}

output "server_ipv4" {
  description = "Public IPv4. Used only for bootstrap SSH before the tailnet is up."
  value       = hcloud_server.mathapp.ipv4_address
}

output "server_ipv6" {
  description = "Public IPv6."
  value       = hcloud_server.mathapp.ipv6_address
}

output "ssh_bootstrap_command" {
  description = "Copy-paste to verify the box is up."
  value       = "ssh root@${hcloud_server.mathapp.ipv4_address}"
}

output "cloud_init_wait_command" {
  description = "Run this on the box to block until first-boot bootstrap finishes."
  value       = "ssh root@${hcloud_server.mathapp.ipv4_address} 'cloud-init status --wait'"
}
