# Proposal: renew-frontend-node-modules-volumes

Status: Draft  
Change ID: `renew-frontend-node-modules-volumes`  
GitHub Issue: `alexandervazquez98/next-gen#306`  
Extends: none  
TDD Policy: `strict_tdd`  
Review Budget: 800 changed lines (user override)

## Intent

The dev `frontend` service uses `./frontend:/app` plus an anonymous `/app/node_modules` volume for hot reload. When `frontend/pnpm-lock.yaml` changes, that stale anonymous volume can hide freshly built image dependencies and leave operators with old `node_modules` after `safe-rebuild.sh`. This is an operational hygiene fix: safe rebuilds should preserve data volumes while automatically renewing build-artifact volumes only when dependency state changes.

## Scope

### In Scope
- Detect frontend lockfile changes in `scripts/safe-rebuild.sh`.
- Conditionally run `docker compose up -d --force-recreate --renew-anon-volumes frontend` only for the dev `frontend` service.
- Add `scripts/refresh-frontend-deps.sh` as an operator recovery script.
- Add RED-first shell tests for lockfile detection, safe-rebuild wiring, and recovery script behavior.
- Add callouts to `docs/backup-restore.md` and `README.md`.

### Out of Scope
- Changing `docker-compose.yml`; the anonymous `/app/node_modules` volume is intentional for dev hot reload.
- Changing `.github/workflows/cd.yml`; auto-deploy is disabled and this change should not alter CD triggers.
- Adding `scripts/README.md` or `docs/operations.md`; use existing documentation homes.
- Changing `frontend-prod`; it has no anonymous volume.
- Adding `--pull` to `docker compose build`.
- Adding a `safe-rebuild.sh --renew-frontend-anon-volumes` flag; manual recovery belongs in `scripts/refresh-frontend-deps.sh`.

## Capabilities

### New Capabilities
- `frontend-dependency-volume-renewal`: operator rebuild flows renew the frontend dev anonymous `node_modules` volume when the frontend lockfile changes, without deleting data volumes.

### Modified Capabilities
- None.

## Approach

- Add POSIX-`sh` helpers to `scripts/safe-rebuild.sh` library mode:
  - `compute_frontend_lockfile_hash()`: returns `sha256sum frontend/pnpm-lock.yaml | awk '{print $1}'`.
  - `frontend_lockfile_changed()`: compares the current hash to `$BACKUP_DIR/frontend-pnpm-lock.sha256`; records pending state without mutating the sentinel until the renew succeeds.
  - `maybe_renew_frontend_anonymous_volume()`: if changed, runs `docker compose up -d --force-recreate --renew-anon-volumes frontend`, then writes the new hash to the sentinel.
- Compute the hash early, after `require_command docker` and after `BACKUP_DIR` is resolved through the existing `validate-env.sh --print-backup-dir` path.
- Wire `maybe_renew_frontend_anonymous_volume()` between `docker compose build` and the existing post-build `docker compose up -d`, or replace that post-build up with a conditional sequence that renews `frontend` first and then starts the remaining project normally.
- Do not touch the pre-backup `docker compose up -d --no-build postgres neo4j backend` path.
- Create `scripts/refresh-frontend-deps.sh` using project script conventions: `#!/bin/sh`, `set -eu`, `usage()`, `--dry-run`, `run()`, `require_command`, and `compose()` wrapper. Its only responsibility is `docker compose up -d --force-recreate --renew-anon-volumes frontend`.
- Tests are RED-first per strict TDD: source library helpers with `SAFE_REBUILD_LIB_ONLY=1`, and stub `docker` via fake `PATH` for end-to-end command assertions.

## Affected Areas

| Area | Impact | Est. LOC | Description |
|---|---:|---:|---|
| `scripts/safe-rebuild.sh` | Modified | +40 / -5 | Hash helpers, sentinel handling, frontend-scoped renew branch. |
| `scripts/test-safe-rebuild-frontend-volume.sh` | New | +170 | RED-first tests for unchanged/changed/dry-run/no destructive volume commands. |
| `scripts/refresh-frontend-deps.sh` | New | +65 | Manual operator recovery script. |
| `scripts/test-refresh-frontend-deps.sh` | New | +130 | RED-first tests for command, dry-run, missing docker, invalid flags. |
| `docs/backup-restore.md` | Modified | +35 | Data-volume vs build-artifact-volume callout and safe rebuild note. |
| `README.md` | Modified | +15 | Troubleshooting pointer to recovery script. |
| `openspec/changes/renew-frontend-node-modules-volumes/proposal.md` | New | +160 | This proposal. |
| `openspec/changes/renew-frontend-node-modules-volumes/specs/frontend-dependency-volume-renewal/spec.md` | New later | +120 | Delta spec in next phase. |

Estimated implementation/docs/tests total: ~580 changed lines, under the 800-line user override.

## Acceptance Criteria

### Safe rebuild
- Given `$BACKUP_DIR/frontend-pnpm-lock.sha256` matches the current `frontend/pnpm-lock.yaml` hash, when `safe-rebuild.sh` runs, then it MUST NOT pass `--renew-anon-volumes`.
- Given the stored hash differs from the current lockfile hash, when `safe-rebuild.sh` runs, then it MUST run `docker compose up -d --force-recreate --renew-anon-volumes frontend` and MUST scope the renewal to `frontend`.
- Given `safe-rebuild.sh --dry-run`, when the lockfile changed, then it MUST print the intended command and MUST NOT execute Docker.
- Given any safe-rebuild path, when Docker commands are recorded, then it MUST NEVER invoke `docker compose down -v` or `docker volume rm`.

### Refresh script
- Given normal execution, when `scripts/refresh-frontend-deps.sh` runs, then it prints `+ docker compose up -d --force-recreate --renew-anon-volumes frontend` and runs that command.
- Given `--dry-run`, when the script runs, then it prints the command and short-circuits without Docker execution.
- Given `docker` is missing, when the script starts, then it exits non-zero with a clear missing-command message.
- Given unsupported flags such as `--skip-neo4j`, when the script parses arguments, then it exits non-zero; no mutually-exclusive flag combos are supported because the script accepts only `--dry-run` and help.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---:|---:|---|
| Renewing anonymous volumes globally could remove future anonymous service volumes. | Med | High | Always scope the command to `frontend`; test command args exactly. |
| Accidentally changing the pre-backup mount `up -d` path could affect backup safety. | Low | High | Wire only after `docker compose build`; add regression test around command order. |
| Sentinel updates before successful renew could mask a failed dependency refresh. | Med | Med | Write `$BACKUP_DIR/frontend-pnpm-lock.sha256` only after the renew command succeeds. |
| Missing lockfile or missing `sha256sum` could fail late. | Low | Med | Validate required file/command up front with explicit errors. |
| Dry-run may accidentally execute the renew command. | Low | High | Use existing `run()` style and stub-Docker tests. |
| Future service anonymous volumes make broad `up` behavior risky. | Med | Med | Keep `--renew-anon-volumes` service-scoped and document why. |
| New recovery script duplicates safe-rebuild behavior and may drift. | Med | Low | Keep script single-purpose; tests assert the same command shape. |
| Docs could imply `docker compose down -v` is acceptable recovery. | Low | High | Explicitly warn against destructive volume deletion in docs and tests. |
| CD auto-deploy being disabled delays production exercise of the path. | Med | Low | Treat manual operator path and dry-run validation as first delivery target. |
| Strict TDD can be bypassed if tests are added after implementation. | Med | Med | Next phase must create failing tests before script edits. |
| The 800-line budget could be exceeded by over-detailed docs/tests. | Med | Med | Keep docs as callouts and scripts narrowly scoped. |

## Rollback Plan

Revert the PR. The sentinel file in `$BACKUP_DIR/frontend-pnpm-lock.sha256` is harmless if left behind. If a bad renew was executed, rerun `docker compose build && docker compose up -d` or the corrected recovery command; no database, API, or schema state is changed.

## Dependencies

- `docker` and `docker compose` on the operator host.
- `sha256sum` available to POSIX shell scripts.
- Existing `scripts/validate-env.sh --print-backup-dir` behavior for durable `BACKUP_DIR` resolution.
- Existing `frontend/pnpm-lock.yaml` and dev `frontend` service name.

## Open Questions

- None. The standalone recovery script is kept; the sentinel lives at `$BACKUP_DIR/frontend-pnpm-lock.sha256`; no `--pull`; hash is computed before build; a fresh capability delta spec is used; safe-rebuild gets automatic detection, not a new manual flag.

## Explicit Non-Goals

- Do not remove the anonymous `/app/node_modules` volume from `docker-compose.yml`.
- Do not add destructive cleanup commands (`docker compose down -v`, `docker volume rm`).
- Do not change production `frontend-prod` compose behavior.
- Do not change CD triggers or deployment automation.
- Do not broaden recovery into general operations documentation.

## Success Criteria

- [ ] Tests prove unchanged lockfile safe-rebuilds do not renew anonymous volumes.
- [ ] Tests prove changed lockfile safe-rebuilds renew only the `frontend` anonymous volume.
- [ ] Tests prove dry-run and missing-docker behavior.
- [ ] Docs explain safe recovery without destructive volume deletion.
- [ ] Total implementation stays under the 800-line review budget.
