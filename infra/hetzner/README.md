# `infra/hetzner` — OpenTofu config for the deployment box

Automates steps 2–3 of [docs/deployment_hetzner.md](../../docs/deployment_hetzner.md):
provision a CX22 in Falkenstein, register the laptop SSH key, attach a
default-deny Hetzner Cloud Firewall, and run a cloud-init script that
installs docker + Tailscale on first boot.

App deploy (step 4 — `git clone`, `scp .env`, `docker compose up`) is
**not** in this stack. That stays a manual scp loop until there's a
reason to invest in CD; see the deployment doc for the procedure.

---

## Why OpenTofu

- Open-source fork of Terraform (MPL 2.0). Same `.tf` syntax, same
  providers, no BSL licence question.
- `hetznercloud/hcloud` provider is the only first-class option for
  declarative Hetzner Cloud anyway.
- State stays local (`terraform.tfstate`, gitignored). One developer,
  one box — remote state is overkill.

If you already have `terraform` installed, every `tofu` command below
works as `terraform` too.

---

## Prereqs

```bash
brew install opentofu                          # macOS
# or: curl -fsSL https://get.opentofu.org/install.sh | sh

brew install --cask tailscale                  # laptop side — see Step 0
open -a Tailscale                              # log in once
```

You'll also need:

- A Hetzner Cloud project + API token (Console → Security → API Tokens,
  Read & Write).
- Your laptop's SSH public key (`~/.ssh/id_ed25519.pub`).
- Your laptop's current public IP, for the bootstrap SSH allowlist
  (`curl -s https://api.ipify.org`).
- *Optional, recommended:* a one-time Tailscale auth key — see [Tailscale
  → Settings → Keys](https://login.tailscale.com/admin/settings/keys).
  When supplied, the box auto-joins the tailnet on first boot.

Tailscale on the laptop is a **host install**, not a docker container —
the host kernel needs the tailnet route so your browser and SSH can use
it. See [Step 0 of the deployment doc](../../docs/deployment_hetzner.md#step-0--your-laptop).

---

## Use

```bash
cd infra/hetzner
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars                       # fill in the four values

tofu init                                      # download the provider
tofu plan                                      # eyeball what'll happen
tofu apply                                     # creates server + firewall + ssh key
```

When apply finishes:

```bash
./scripts/connect.sh                           # cheatsheet of every
                                               # way to reach the box

tofu output ssh_bootstrap_command              # raw form, same info
tofu output cloud_init_wait_command            # block until bootstrap done
```

If you supplied `tailscale_auth_key`, the box will be in the tailnet
within ~30s of the SSH succeeding; check from the laptop:

```bash
tailscale status | grep <server_name>
```

Then continue with step 4 of the deployment doc (clone the repo on the
box, `scp .env`, `docker compose up -d`).

---

## After Tailscale is live

The doc recommends deleting the public SSH firewall rule once Tailscale
SSH is verified. To do that here, edit `terraform.tfvars`:

```hcl
allowed_ssh_cidrs = []
```

Then `tofu apply`. The dynamic block in `firewall.tf` will drop the
TCP/22 rule, leaving only ICMP open to the public internet.

---

## Tearing down

```bash
tofu destroy
```

Hetzner stops billing immediately. The Supabase data is untouched —
the box is stateless by design.

---

## What's in this directory

| File | Purpose |
|---|---|
| [versions.tf](versions.tf) | OpenTofu + provider version pins |
| [variables.tf](variables.tf) | All input variables, documented |
| [ssh.tf](ssh.tf) | `hcloud_ssh_key` resource |
| [firewall.tf](firewall.tf) | `hcloud_firewall` — SSH from laptop + ICMP |
| [server.tf](server.tf) | `hcloud_server` — the CX22 itself |
| [cloud-init.yaml](cloud-init.yaml) | First-boot bootstrap script |
| [outputs.tf](outputs.tf) | What to copy-paste after apply |
| [terraform.tfvars.example](terraform.tfvars.example) | Template for tfvars |
| [scripts/connect.sh](scripts/connect.sh) | Prints SSH / URL cheatsheet from tofu output |

---

## What this does NOT do (yet)

Same scope as step 1–3 of the deployment doc. Not covered here:

- App deploy (step 4) — `scp .env`, `docker compose up`. Manual.
- TLS / Caddy / public exposure (step 5 path B). Defer until needed.
- Auth on the API. Reachability is the auth while the tailnet is the
  only route in.
- math-ui co-deployment. Sketched in the doc but not in compose yet.
- Backups. Supabase backs up itself; the box is stateless.
- A second region / HA / DR. Out of scope for a single-developer setup.
