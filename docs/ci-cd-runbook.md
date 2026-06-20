# CI/CD Runbook

> **Audience:** on-call operators and reviewers of the next-gen CI/CD pipeline.
>
> **Related docs:**
> - `docs/self-hosted-runner.md` — runner install, registration, hardening, rotation.
> - `scripts/safe-rebuild.sh` — deploy entry point (unchanged in v1).
> - `scripts/pre-rebuild-backup.sh` — captures the pre-rebuild backup.
> - `scripts/validate-env.sh` — `.env` contract + `BACKUP_DIR` check.
> - `scripts/ci-cd-check-runner-contract.sh` — runner contract validator invoked by the CD workflow.
> - `.github/workflows/cd.yml` — the CD lane.
> - `openspec/changes/ci-cd-pipeline/specs/ci-cd-pipeline/spec.md` — capability spec (R8, R9, R10).
> - Engram `architecture/cicd-rollback-policy` — v1 decision: no auto-rollback.
> - Engram `architecture/cicd-design-decisions` — locked design choices (alert channel, concurrency group, chain strategy).

## How CD fires

The CD workflow (`.github/workflows/cd.yml`) runs **only on push to `main`**
and via `workflow_dispatch` with an optional `dry_run: boolean` input. The
concurrency group is `cd-main` with `cancel-in-progress: false` — an
in-flight deploy is never cancelled, even if a new commit lands.

Trigger flow:

1. `push` to `main` lands (this happens after the integrated PR1..PR6 chain
   fast-forwards into `main`).
2. CD job starts on the self-hosted runner (`runs-on: [self-hosted, linux,
   x64, production, next-gen, cd]`).
3. Runner contract is validated
   (`sh scripts/ci-cd-check-runner-contract.sh`).
4. `.env` is validated
   (`sh scripts/validate-env.sh --check-backup-dir`).
5. Pre-flight dry-run prints the deploy plan in the job log
   (`sh scripts/safe-rebuild.sh --dry-run`).
6. Real deploy runs
   (`sh scripts/safe-rebuild.sh`) — unless `dry_run: true` was supplied.
7. On any failure, the workflow opens a GitHub Issue labeled `cd-failure`
   pointing to the run URL, commit SHA, and this runbook.

The smoke lane (PR5) is the **deployment gate** in v1. CD does not re-run
smoke; it trusts PR5's `cicd/smoke-playwright` result that already merged.

## Deployment

The deploy procedure is identical to a manual `safe-rebuild.sh` invocation;
the CD workflow simply automates the same steps an operator would take.

### What `safe-rebuild.sh` does

In order:

1. Validates `.env` against `.env.example` via `scripts/validate-env.sh`.
2. Resolves `BACKUP_DIR` (env var or `.env`, default `.docker/backups`).
3. Refuses unsafe `BACKUP_DIR` paths (`/tmp`, `/var/tmp`, `..`, etc.).
4. Ensures `BACKUP_DIR` exists and is writable.
5. Validates `docker compose config --quiet`.
6. Brings up the data tier (`postgres`, `neo4j`, `backend`) without rebuilding.
7. Verifies `/backups` is writable inside each container.
8. Runs `scripts/pre-rebuild-backup.sh` — captures a PostgreSQL dump and
   either a Neo4j APOC export or an offline-dump-required note. Files are
   written to `$BACKUP_DIR` with `postgres_<UTC-timestamp>.dump`,
   `neo4j_<UTC-timestamp>.cypher` / `_dump/` / `_offline-dump-required.txt`.
9. Builds images with `docker compose build`.
10. Brings up the full stack with `docker compose up -d`.
11. Runs the ICMP latency/jitter and availability-source migrations.
12. Prints `docker compose ps`.

The script **never** runs `docker compose down -v`, never deletes a
volume, never removes a host directory. Pre-rebuild backups are retained
indefinitely until `BACKUP_DIR` retention is configured (operator action).

### What the CD workflow does beyond `safe-rebuild.sh`

- Asserts the runner contract (Docker, Compose v2, `BACKUP_DIR`, `.env`,
  `gh` auth).
- Sets `concurrency: { group: cd-main, cancel-in-progress: false }`.
- Opens a `cd-failure` GitHub Issue on any step failure.
- Provides a `dry_run: true` dispatch input that skips the real deploy
  while still running every pre-flight check.

### Operator-initiated dry-run

Useful before a scheduled deploy or after a risky merge:

1. Open `.github/workflows/cd.yml` → Run workflow.
2. Set `dry_run: true`.
3. Watch the job log; the dry-run prints every step without changing
   state. Confirm the plan matches expectations, then either re-run with
   `dry_run: false` (not currently exposed — use a manual push to `main`)
   or proceed with the manual fallback below.

## Manual deploy fallback

If the self-hosted runner is offline, the dispatch cannot land, and the
issue is not blocking critical fixes:

```sh
# From the production endpoint, as the runner user:
cd /opt/actions-runner/_work/next-gen/next-gen   # or the canonical repo path
git fetch origin
git checkout main
git pull --ff-only
sh scripts/validate-env.sh --check-backup-dir
sh scripts/safe-rebuild.sh --dry-run             # sanity preview
sh scripts/safe-rebuild.sh                       # real deploy
```

The CD workflow does not retry or interfere with a manual run, but it
will open a `cd-failure` issue if a parallel `push` event triggers it.

## Failure recovery

When `safe-rebuild.sh` exits non-zero, the CD workflow fails and opens a
`cd-failure` GitHub Issue. **No automated rollback runs in v1** (see
[Rollback policy](#rollback-policy)).

### Step-by-step recovery

1. **Open the `cd-failure` issue.** Note the run URL, commit SHA, and the
   captured `safe-rebuild.sh` output (issue body contains the last 200
   lines plus a runbook pointer).
2. **Inspect `BACKUP_DIR`.** The pre-rebuild backup was captured at the
   start of the failed deploy:
   ```sh
   ls -lt .docker/backups/ | head -20
   # Pick the most recent timestamp matching the failed deploy.
   ```
3. **Diagnose the failure.** Common causes:
   - Compose service healthcheck never turned green → check container logs
     via `docker compose logs --tail=200 <service>`.
   - Migration script failed → re-run the failing migration manually
     after restoring the DB (see step 5).
   - `.env` invalid → `sh scripts/validate-env.sh` will print which key.
   - Disk full → check `df -h $BACKUP_DIR`.
4. **Stop services if the partial deploy left the stack in a broken state:**
   ```sh
   docker compose ps
   docker compose stop backend frontend   # do not use 'down -v'
   ```
5. **Restore the database from the pre-rebuild backup** (PostgreSQL only;
   Neo4j restore is offline-only):
   ```sh
   BACKUP_DIR=.docker/backups
   LATEST_PG=$(ls -t "$BACKUP_DIR"/postgres_*.dump | head -1)
   docker compose up -d postgres
   docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists "$LATEST_PG"
   ```
   Neo4j restore requires a maintenance window. See
   `scripts/pre-rebuild-backup.sh --neo4j-offline` for the offline dump
   pattern; restore is the inverse under `neo4j-admin database load`.
6. **Re-run `safe-rebuild.sh`** once the underlying issue is fixed.
   The pre-rebuild backup runs again, so the previous one is preserved.
7. **Close the `cd-failure` issue** with a one-line summary of the root
   cause and the SHA that recovered.

If the failure is on the host (not the application), the smoke lane will
catch it on the next PR. If the failure is repeatable on every deploy,
**disable the CD workflow** (Settings → Actions → `cd` → Disable) until
the root cause is fixed.

## Rollback policy

**v1 ships with NO automatic rollback.** This decision is locked in
Engram `architecture/cicd-rollback-policy` and the proposal
(`openspec/changes/ci-cd-pipeline/proposal.md`, Risks and Rollback Plan).

| Signal | v1 behavior |
|---|---|
| Smoke failure (PR5) | Merge blocked; workflow fails pre-merge. |
| CD deploy failure | Workflow fails; `cd-failure` issue opened; human restores. |
| Post-deploy regression | Workflow does not detect this in v1. Operators rely on monitoring and the issue. |
| `BACKUP_DIR` lost | Workflow fails on contract step; human restores from offline copy. |

Why no auto-rollback in v1: `safe-rebuild.sh` already captures a
pre-rebuild backup (PostgreSQL dump + Neo4j dump). Adding image-tag
rollback or automated DB restore in v1 would explode the PR6 review budget
and ship risky new code without proven need. Image-tag rollback and full
DB restore automation are explicitly **deferred to a future change**.

## Alert acknowledgment

The CD workflow opens a GitHub Issue labeled `cd-failure` on any failed
step. Triage procedure:

1. **Acknowledge within 15 minutes** of the issue opening (assign yourself,
   add a `triage` label if your team uses one).
2. **Read the issue body**: it contains the run URL, commit SHA + message,
   the last 200 lines of `safe-rebuild.sh` output, and a link back to this
   runbook.
3. **Decide within 30 minutes**:
   - **Recoverable in <1h** → follow [Failure recovery](#failure-recovery),
     then close the issue with root cause + recovery SHA.
   - **Not recoverable in <1h** → disable the CD workflow to prevent
     further failed deploys, escalate to the project owner, leave the
     issue open with a status update every 4h.
   - **False positive** (e.g., transient runner network error) → comment
     with the manual deploy SHA and close.
4. **Never close without a comment.** The audit trail matters.
5. **Never delete the issue.** Close it, but keep it for postmortems.

If the issue is reopened by a subsequent failure, do not close it as a
duplicate — link the new run and add a timeline comment.

## On-call checklist (first 5 minutes)

Run through this list the moment a `cd-failure` issue lands in your
inbox:

1. [ ] **Read the issue body.** Identify the run URL and the failed step.
2. [ ] **Confirm the deploy is real**, not a workflow_dispatch dry-run.
       Check `event_name` in the issue body.
3. [ ] **Check `BACKUP_DIR` is intact.**
       `ls -lt .docker/backups/ | head -5`. If missing, escalate
       immediately (host-level failure).
4. [ ] **Check the runner is online.**
       `sudo systemctl status actions.runner.*` on the runner host. If
       down, restart the service.
5. [ ] **Read the last 200 lines of `safe-rebuild.sh` output** (already
       captured in the issue). Identify the failing command.
6. [ ] **Check `docker compose ps`** for partial state.
7. [ ] **Decide**: recoverable in <1h or escalate. See Alert
       acknowledgment above.
8. [ ] **If recoverable**: run [Failure recovery](#failure-recovery).
9. [ ] **If escalating**: disable the CD workflow and notify the project
       owner.
10. [ ] **Post a status comment** on the issue every 30 minutes until
       resolved or escalated.

## Cross-references

- Proposal: `openspec/changes/ci-cd-pipeline/proposal.md`
- Spec: `openspec/changes/ci-cd-pipeline/specs/ci-cd-pipeline/spec.md`
- Design: `openspec/changes/ci-cd-pipeline/design.md`
- Tasks: `openspec/changes/ci-cd-pipeline/tasks.md`
