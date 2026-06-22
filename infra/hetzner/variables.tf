# All inputs to the Hetzner stack. Sensitive values are marked so they
# stay out of `tofu plan` / `tofu show` output by default.
#
# Fill them in via `terraform.tfvars` (gitignored) — see
# terraform.tfvars.example for the template.

variable "hcloud_token" {
  description = "Hetzner Cloud API token. Create one in the Hetzner Console → Security → API Tokens (Read & Write)."
  type        = string
  sensitive   = true
}

variable "server_name" {
  description = "Hetzner server name. Shows up in the Hetzner console + as the box hostname."
  type        = string
  default     = "mathapp-prod"
}

variable "server_type" {
  description = "Hetzner server type. cx33 = 4 vCPU / 8 GB / 80 GB SSD, shared x86 (~€8.49/mo net). Upgrade from cx23 (2 vCPU / 4 GB) — deferred 2026-06-22 because fsn1 had no 8 GB migration capacity. Apply when it returns; resize is in-place (lifecycle ignore_changes on user_data)."
  type        = string
  default     = "cx33"
}

variable "location" {
  description = "Hetzner datacenter location. fsn1 (Falkenstein) and nbg1 (Nuremberg) are closest to Supabase eu-west-1."
  type        = string
  default     = "fsn1"
}

variable "image" {
  description = "Base image slug. Ubuntu 24.04 LTS is what the deploy doc assumes."
  type        = string
  default     = "ubuntu-24.04"
}

variable "ssh_public_key" {
  description = "Contents of the laptop's SSH public key (e.g. cat ~/.ssh/id_ed25519.pub). Used for the initial bootstrap SSH; once Tailscale SSH is up you can stop relying on this."
  type        = string
}

variable "ssh_key_name" {
  description = "Display name for the SSH key in the Hetzner console."
  type        = string
  default     = "mathapp-laptop"
}

variable "allowed_ssh_cidrs" {
  description = "CIDRs allowed to reach port 22 on the box during bootstrap. Tighten to your laptop's /32 — once Tailscale SSH works you can set this to [] to close public SSH entirely."
  type        = list(string)
  default     = []
}

variable "tailscale_auth_key" {
  description = "Optional one-time Tailscale auth key (tskey-auth-...). When set, cloud-init runs `tailscale up --ssh --authkey=...` so the box joins the tailnet on first boot with no manual step. Leave empty to install the binary only and run `tailscale up` manually after first SSH."
  type        = string
  default     = ""
  sensitive   = true
}

variable "tailscale_hostname" {
  description = "Hostname Tailscale advertises. Defaults to server_name."
  type        = string
  default     = ""
}
