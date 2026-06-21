# Design: renew-frontend-node-modules-volumes

Change ID: `renew-frontend-node-modules-volumes`  
GitHub Issue: `alexandervazquez98/next-gen#306`  
TDD Policy: `strict_tdd`

## 1. Approach summary

Implement a POSIX-`sh` script change that treats frontend `node_modules` as a rebuild artifact, not data. `scripts/safe-rebuild.sh` will hash `frontend/pnpm-lock.yaml`, compare it with `$BACKUP_DIR/frontend-pnpm-lock.sha256`, and, only when changed, renew the dev `frontend` anonymous volume with a service-scoped `docker compose up -d --force-recreate --renew-anon-volumes frontend`. A new `scripts/refresh-frontend-deps.sh` gives operators the same narrow recovery command manually. No compose, prod overlay, or CD workflow changes.

Flow:

```text
safe-rebuild.sh -> hash helpers -> docker compose build
                -> maybe renew frontend anon volume -> docker compose up -d

refresh-frontend-deps.sh -> docker compose up -d --force-recreate --renew-anon-volumes frontend

frontend/pnpm-lock.yaml -> sha256 -> sentinel compare -> conditional frontend recreate
```

## 2. File changes table

| File | Action | Description |
|---|---|---|
| `scripts/safe-rebuild.sh` | Modify | Add lockfile hash helpers, sentinel handling, and frontend-scoped renew wiring. |
| `scripts/test-safe-rebuild-frontend-volume.sh` | New | RED-first helper and end-to-end shell tests. |
| `scripts/refresh-frontend-deps.sh` | New | Manual dependency-volume recovery script. |
| `scripts/test-refresh-frontend-deps.sh` | New | RED-first command-shape and CLI tests. |
| `docs/backup-restore.md` | Modify | Explain data volumes vs build-artifact anonymous volume recovery. |
| `README.md` | Modify | Add troubleshooting pointer to the refresh script. |

## 3. Component details

`safe-rebuild.sh` remains `#!/bin/sh` + `set -eu`; avoid bash arrays, `[[ ]]`, `pipefail`, process substitution, and `local`. Add helpers before `SAFE_REBUILD_LIB_ONLY` so tests can source them.

| Component | Interface | Logic / errors |
|---|---|---|
| `compute_frontend_lockfile_hash()` | Prints current SHA-256 hash. | Require readable `frontend/pnpm-lock.yaml`; use `sha256sum ... | awk '{print $1}'`; fail clear if missing. Add `require_command sha256sum` in main before use. |
| `frontend_lockfile_changed()` | Returns 0 when renew is needed, 1 when unchanged; stores current hash in a global such as `frontend_lockfile_hash`. | Compare current hash with `$backup_dir/frontend-pnpm-lock.sha256`; missing sentinel counts as changed. Do not write here. |
| `maybe_renew_frontend_anonymous_volume()` | Runs/no-ops based on `frontend_lockfile_changed`. | If changed, `run docker compose up -d --force-recreate --renew-anon-volumes frontend`; after successful non-dry-run renew, write `printf '%s\n' "$frontend_lockfile_hash" > "$backup_dir/frontend-pnpm-lock.sha256"`. In dry-run, print the command and a sentinel-write note only. |

Main wiring: after `require_command docker`, also require `sha256sum`; after `backup_dir=$(sh scripts/validate-env.sh --print-backup-dir)` and `ensure_host_backup_dir`, compute/compare sentinel state. Do not alter the pre-backup mount command at current L188. Keep current L205 `run docker compose build`, call `maybe_renew_frontend_anonymous_volume` immediately after it, then keep current L206 `run docker compose up -d` for the rest of the project. Sentinel write timing is after successful renew only, so failed Docker commands do not mask stale dependency state.

`scripts/refresh-frontend-deps.sh`: `sh scripts/refresh-frontend-deps.sh [--dry-run]`; support `-h|--help`; reject all other flags with usage + exit 2. Use project conventions: `usage()`, `dry_run=0`, `run()`, `require_command docker`, `compose()`. Normal command shape must be exactly `docker compose up -d --force-recreate --renew-anon-volumes frontend`; dry-run prints `+ ...` and executes nothing.

Sentinel: `$BACKUP_DIR/frontend-pnpm-lock.sha256`; single line hex SHA-256 with trailing newline; created/updated only after successful frontend anonymous-volume renew. Leaving it behind is harmless.

## 4. Tests and TDD order

Strict TDD: commit tests first while scripts fail. `scripts/test-safe-rebuild-frontend-volume.sh` uses `SAFE_REBUILD_LIB_ONLY=1` for helper tests and fake `PATH`/stub `docker` for flow tests. Cover: unchanged sentinel never emits `--renew-anon-volumes`; changed sentinel emits exactly the frontend-scoped renew command; dry-run prints but does not execute Docker; no path emits `docker compose down -v` or `docker volume rm`; renew occurs after build and before the final broad `up -d`.

`scripts/test-refresh-frontend-deps.sh` uses stub `docker`; assert normal command, dry-run short-circuit, missing/broken docker exits non-zero with missing-command messaging, and invalid flags such as `--skip-neo4j` exit 2.

## 5. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Change detection | SHA-256 of `frontend/pnpm-lock.yaml` | Content hash avoids mtime/git false positives on deploy hosts. |
| Renew scope | `frontend` service only | Prevents future anonymous-volume footguns outside the dev frontend. |
| Sentinel location | `$BACKUP_DIR/frontend-pnpm-lock.sha256` | Durable with existing safe-rebuild backup-dir resolution. |
| Prod overlay | No change | `frontend-prod` has no anonymous volume; renewal is a dev-service no-op there. |
| Recovery | Dedicated narrow script | Keeps manual operator fix tested and avoids destructive `down -v` advice. |

## 6. Rollback plan

Revert the PR. The sentinel is harmless if left behind. If a bad renew ran, rebuild and rerun the corrected `docker compose up -d --force-recreate --renew-anon-volumes frontend`; no database/API/schema state is affected.

## 7. Out of scope

Removing the anonymous compose volume; touching `docker-compose.prod.yml`/`frontend-prod`; changing CD workflows; adding `--pull`; adding a `safe-rebuild.sh` manual flag; destructive volume cleanup.

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---:|---|
| `--renew-anon-volumes` becomes service-wide | Med | Exact command tests require final arg `frontend`. |
| Sentinel write before failed renew | Med | Write only after successful renew. |
| Sentinel durability assumes stable `BACKUP_DIR` | Low | Use existing validated backup-dir path. |
| Prod expectations confusion | Low | Document that `frontend-prod` has no anonymous volume. |
| Script drift between auto and manual paths | Med | Tests assert shared command shape. |

## 9. Open questions

None blocking.
