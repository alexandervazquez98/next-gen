# Self-Hosted Runner Setup

> **Audience:** operators responsible for installing, hardening, and rotating the
> production self-hosted GitHub Actions runner that hosts the `cd` lane
> (`openspec/changes/ci-cd-pipeline/specs/ci-cd-pipeline/spec.md` R8).
>
> **Related docs:**
> - `docs/ci-cd-runbook.md` — operational runbook (deploy procedure, failure recovery, alert triage).
> - `scripts/ci-cd-check-runner-contract.sh` — contract validator the CD workflow calls before deploy.
> - `openspec/changes/ci-cd-pipeline/specs/ci-cd-pipeline/spec.md` — capability spec.
> - `openspec/changes/ci-cd-pipeline/design.md` — design decisions D2 (self-hosted) and D8 (chain tooling).

## Overview

The CD lane runs on a **self-hosted GitHub Actions runner** registered against
this repository with the labels `self-hosted`, `linux`, `x64`, `production`,
`next-gen`, `cd`. The runner lives on the production endpoint and calls the
existing `scripts/safe-rebuild.sh` deploy path. No third-party runner
provider is involved in v1.

Why self-hosted:

1. **Deploy target is the runner host itself.** The runner calls
   `docker compose` against the local daemon and writes to the local
   `BACKUP_DIR`. A hosted runner cannot do either without mounting the
   production disk into ephemeral cloud storage.
2. **The CD workflow trusts `safe-rebuild.sh`.** That script already requires
   Docker, Docker Compose v2, `BACKUP_DIR`, and `.env`. Putting CD on the same
   host as the manual deploy path means the automation and the operator
   fallback share one trusted environment.
3. **No secret exfiltration.** `.env` and host-local secrets never leave the
   endpoint. GitHub Secrets cover only the `GITHUB_TOKEN` for issue creation.

Expected labels: `self-hosted`, `linux`, `x64`, `production`, `next-gen`, `cd`.
All six MUST be present; the workflow `runs-on` filter requires them and the
runner contract script re-validates them.

## Prerequisites

Install before registering the runner:

| Prerequisite | Why it is required |
|---|---|
| Linux x86_64 host with systemd | The runner is installed as a `systemd` service for restart-on-failure semantics. |
| Docker Engine ≥ 24.x | `safe-rebuild.sh` invokes `docker compose` (v2 plugin), which is bundled with recent Docker Engine releases. |
| Docker Compose v2 | `docker compose version` must report `v2.x.x`. The runner contract script rejects v1. |
| A durable `BACKUP_DIR` (default `.docker/backups`) | The CD workflow captures a pre-rebuild backup before touching containers. The directory must be on the host (not inside a container). |
| A host-resident `.env` | Loaded by `safe-rebuild.sh` for production secrets (`POSTGRES_PASSWORD`, `NEO4J_PASSWORD`, `JWT_SECRET_KEY`, etc.). Must mirror `.env.example` and pass `scripts/validate-env.sh`. |
| `gh` CLI authenticated | Used by the CD workflow to open `cd-failure` issues. Run `gh auth login` once. |
| Outbound HTTPS to `github.com` and `api.github.com` | Required for runner registration and job polling. |

Hardware baseline: 4 vCPU, 8 GiB RAM, 50 GiB free disk in `BACKUP_DIR`. The
compose stack needs ~3 GiB peak during image builds.

## Installation

The runner is the standard GitHub `actions-runner` tarball installed under
`/opt/actions-runner`. Steps:

```sh
# 1. Create a dedicated runner user (least privilege).
sudo useradd --system --shell /bin/bash --home /opt/actions-runner runner

# 2. Add the runner user to the docker group so it can call the local daemon
#    without sudo. NEVER run the runner as root.
sudo usermod -aG docker runner

# 3. Download and extract the pinned runner version.
sudo -u runner mkdir -p /opt/actions-runner
sudo -u runner curl -sSLf -o /tmp/runner.tar.gz \
  "https://github.com/actions/runner/releases/download/v2.319.1/actions-runner-linux-x64-2.319.1.tar.gz"
sudo -u runner tar xzf /tmp/runner.tar.gz -C /opt/actions-runner

# 4. Lock down the workdir (runner writes checked-out repo here).
sudo chmod 700 /opt/actions-runner
```

## Registration and labels

Obtain a registration token from the repository (Settings → Actions → Runners
→ New self-hosted runner). The token is short-lived; rotate it after every
registration and never commit it.

```sh
# 5. Configure the runner. Replace placeholders before running.
sudo -u runner /opt/actions-runner/config.sh \
  --url https://github.com/alexandervazquez98/next-gen \
  --token "<registration-token-from-github>" \
  --labels self-hosted,linux,x64,production,next-gen,cd \
  --unattended \
  --replace

# 6. Install and start the systemd service.
sudo /opt/actions-runner/svc.sh install runner
sudo /opt/actions-runner/svc.sh start
sudo systemctl status actions.runner.*   # confirm 'active (running)'
```

The runner is now visible at Settings → Actions → Runners. Confirm all six
labels are present; if any are missing, re-run `config.sh --labels` with the
full label list (comma-separated, no spaces).

## Token rotation

Registration tokens expire (~1 hour) and can be revoked. Rotation procedure:

1. Generate a fresh token at Settings → Actions → Runners → New self-hosted
   runner. **Do not reuse a leaked token.**
2. Stop the service: `sudo /opt/actions-runner/svc.sh stop`.
3. Remove the runner from GitHub: `sudo /opt/actions-runner/config.sh remove --token "<fresh-token>"`.
4. Re-register with step 5 above and start the service.
5. Verify a dispatch `dry_run: true` job lands on the new runner.

Cadence: rotate at least every 90 days, immediately on personnel changes,
and any time the runner host leaves a trusted network.

## Hardening checklist

Run every item before declaring the runner production-ready. Re-check on the
same cadence as token rotation.

- [ ] Runner user is **not root** (`id runner` shows `uid` under 1000).
- [ ] Runner user is in the `docker` group only — no other supplementary
      groups, no sudoers entry.
- [ ] `/opt/actions-runner` is `chmod 700` and owned by `runner:runner`.
- [ ] `BACKUP_DIR` is on a separate partition or volume with capacity alerts.
- [ ] `.env` is `chmod 600`, owned by `runner`, never world-readable.
- [ ] The runner systemd unit has `NoNewPrivileges=yes`,
      `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`.
- [ ] Outbound network egress is allowlisted to `github.com`, `api.github.com`,
      `objects.githubusercontent.com`, and the project's container registry
      (if used). No wildcard egress.
- [ ] OS security patches applied within the last 30 days.
- [ ] Docker Engine and Compose are within the supported release window.
- [ ] `gh auth status` reports `Logged in to github.com as <org-bot>` with
      `repo` and `write:issues` scopes.
- [ ] Host firewall denies inbound SSH from outside the bastion subnet.
- [ ] Audit logging enabled: `journalctl -u actions.runner.*` is shipped to
      the central log store.
- [ ] Log redaction: workflow steps never echo `.env` contents; the
      `safe-rebuild.sh` script prints only file paths and exit codes.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Runner shows offline in GitHub | `actions.runner.*` service stopped | `sudo systemctl status actions.runner.*` → `sudo systemctl start actions.runner.*` |
| Workflow `runs-on` never matches | Missing or stale labels | `sudo /opt/actions-runner/config.sh --labels self-hosted,linux,x64,production,next-gen,cd` |
| Runner contract step fails: "docker is not installed" | Docker Engine removed or PATH drift | Reinstall Docker Engine and confirm `command -v docker` works for the runner user |
| Runner contract step fails: "Docker Compose v2 required" | Plugin not installed | `sudo apt-get install docker-compose-plugin` (or distro equivalent) |
| Runner contract step fails: "BACKUP_DIR is not writable" | Disk full or permissions | `df -h $BACKUP_DIR`; `sudo chown -R runner:runner $BACKUP_DIR && sudo chmod 750 $BACKUP_DIR` |
| Runner contract step fails: ".env not found" | Missing or wrong location | `ls -la /opt/actions-runner/.env`; copy from `.env.example` and populate secrets |
| Runner contract step fails: "gh is not authenticated" | Token expired | `sudo -u runner gh auth login` (or refresh the token) |
| `docker compose` hangs mid-deploy | Docker daemon hung | `sudo systemctl restart docker`; if persistent, check `journalctl -u docker` |
| Deploy job stays queued | No runner matches all six labels | Verify labels via `sudo /opt/actions-runner/config.sh list`; the label list must match exactly |
| `safe-rebuild.sh` exits non-zero | See the cd-failure issue body for the captured output and follow `docs/ci-cd-runbook.md#failure-recovery` |

## Disabling a compromised runner

If a runner is suspected to be compromised (token leak, unpatched host,
unauthorized access):

1. **Stop the service immediately** on the runner host:
   `sudo /opt/actions-runner/svc.sh stop && sudo systemctl disable actions.runner.*`.
2. **Remove the runner from GitHub**: Settings → Actions → Runners →
   locate the runner → Remove. This revokes its long-lived credentials.
3. **Revoke any associated tokens** (registration token, PAT used by `gh`).
4. **Inspect** `/opt/actions-runner/_diag/`, `journalctl`, and audit logs for
   the intrusion window.
5. **Reinstall** on a clean host before re-registering.
6. **File an incident** and notify the project owners. Pause CD deploys
   (Settings → Actions → disable the `cd` workflow) until the host is
   rebuilt.

## Acceptance evidence

Per the strict TDD policy in `openspec/config.yaml`, this task uses
**manual evidence**: the runner walkthrough is documented end-to-end and
verified by the contract script (`scripts/ci-cd-check-runner-contract.sh`)
which the CD workflow calls before every deploy. See
`openspec/changes/ci-cd-pipeline/specs/ci-cd-pipeline/spec.md` R10 for the
scenarios this guide satisfies.
