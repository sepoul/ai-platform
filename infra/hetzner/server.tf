# The actual VM. Pulls in the SSH key, firewall, and cloud-init script
# defined in the sibling files. One server, one role — provisioning a
# second box is a `for_each`-or-copy decision for later.

resource "hcloud_server" "mathapp" {
  name         = var.server_name
  server_type  = var.server_type
  location     = var.location
  image        = var.image
  ssh_keys     = [hcloud_ssh_key.laptop.id]
  firewall_ids = [hcloud_firewall.mathapp.id]

  # Re-rendered on every change to cloud-init.yaml. That changes the
  # `user_data` hash → Terraform wants to recreate the server, which
  # is what you want for a config drift: the IaC should be the source
  # of truth on first boot. After the box is live, the right loop is
  # ssh-in-and-fix, not destroy-and-recreate; once you're past day one,
  # use `lifecycle.ignore_changes = [user_data]` if needed.
  user_data = templatefile("${path.module}/cloud-init.yaml", {
    TAILSCALE_AUTH_KEY = var.tailscale_auth_key
    TAILSCALE_HOSTNAME = coalesce(var.tailscale_hostname, var.server_name)
  })

  labels = {
    managed-by = "opentofu"
    app        = "mathapp"
  }

  # Past day one: the box is bootstrapped, so `user_data` (cloud-init) only
  # ever ran at first boot and can't be applied in place. Ignore its drift
  # so routine changes (e.g. a `server_type` resize) happen IN-PLACE instead
  # of destroy-and-recreate. (The live box was built from the pre-82866da
  # cloud-init — docker-compose-plugin — and the yaml was corrected to
  # docker-compose-v2 minutes after creation; that historical, first-boot-only
  # diff was the recreate trigger.) To re-bootstrap from new cloud-init,
  # recreate deliberately: `tofu apply -replace=hcloud_server.mathapp`.
  lifecycle {
    ignore_changes = [user_data]
  }
}
