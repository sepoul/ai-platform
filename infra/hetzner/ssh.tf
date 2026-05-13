# SSH key registered in the Hetzner project. Referenced by the server
# resource so root@<box> works on first boot — before Tailscale SSH
# takes over.

resource "hcloud_ssh_key" "laptop" {
  name       = var.ssh_key_name
  public_key = var.ssh_public_key
}
