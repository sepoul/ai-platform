# OpenTofu + hcloud provider pins.
#
# Pinned to a known-good major to keep `tofu plan` deterministic across
# laptops. Bump intentionally, not by accident — provider 1.x → 2.x in
# the past has renamed attributes on `hcloud_server`.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.48"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}
