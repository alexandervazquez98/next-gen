# Apply Progress — renew-frontend-node-modules-volumes

- Change: `renew-frontend-node-modules-volumes`
- Issue: `alexandervazquez98/next-gen#306`
- Branch / worktree: `fix/306-renew-frontend-node-modules-volumes` @ `/home/alex/dev/next-gen/worktrees/fix-306-renew-frontend-node-modules-volumes`
- Cycle base SHA: `aa852a8` (last commit on `main` before the branch diverged)
- Strict TDD: ON
- Mode: OpenSpec + Engram hybrid (single PR; 800-line override accepted)

## TDD Cycle Evidence

| Task | Phase | Commit | Subject | RED | GREEN |
|---|---|---|---|---|---|
| T1 | RED | `486fb07` | test(scripts): add RED-first bash tests for frontend volume renewal | committed while helpers/wiring absent (test file itself exits non-zero before sourcing) | n/a |
| T2 | RED | `560cb80` | test(scripts): add RED-first bash tests for refresh-frontend-deps CLI | committed while refresh script absent (`sh scripts/refresh-frontend-deps.sh` is "not found") | n/a |
| T3 | GREEN helpers | `f76aef6` | feat(scripts): add frontend lockfile hash helpers to safe-rebuild | n/a (test from T1) | 3 helper tests pass; wiring tests still fail until T4 |
| T4 | GREEN wiring | `7c39607` | feat(scripts): conditionally renew frontend anon volume in safe-rebuild | n/a (test from T1) | end-to-end R1-R4 tests pass |
| T5 | GREEN refresh | `a790921` | feat(scripts): add refresh-frontend-deps operator recovery script | n/a (test from T2) | R5-R8 CLI tests pass |
| T6 | DOCS | `4910a79` | docs(backup-restore): clarify data-volume vs build-artifact volume recovery | n/a | callout present; grep proves |
| T7 | DOCS | `8ee56de` | docs(readme): point operators to refresh-frontend-deps for stale deps | n/a | one `refresh-frontend-deps` hit in `README.md` |
| T8 | SDD | `1cdb651` | chore(sdd): add apply-phase CHANGELOG to renew-frontend-node-modules-volumes tasks | n/a | CHANGELOG table maps T1-T8 to commits; matches `git log` |

### Strict-TDD proof

`git log --oneline aa852a8..HEAD` shows the two `test(scripts):` commits (`486fb07`, `560cb80`) preceding all three `feat(scripts):` commits (`f76aef6`, `7c39607`, `a790921`), satisfying the spec's "T1 + T2 commits precede T3 + T4 + T5 in git log" invariant.

## Completed Tasks

### T1 — RED-first bash tests for safe-rebuild wiring

- New file: `scripts/test-safe-rebuild-frontend-volume.sh` (408 LOC, executable)
- 8 sandbox-style end-to-end scenarios covering R1 (matching sentinel skips), R2 (changed sentinel renews only `frontend`), R3 (dry-run prints but no `docker` exec), R4 (no `docker compose down -v` and no `docker volume rm` in recorded `docker.log` or planned `+` lines), plus 3 helper-level tests for `compute_frontend_lockfile_hash`, `frontend_lockfile_changed`, `maybe_renew_frontend_anonymous_volume`
- RED proven: test exits non-zero while `safe-rebuild.sh` lacks the helpers
- Stub `docker` via fake `PATH`; copy `.env.example`, `.env`, and helper scripts into a per-test temp dir to bypass `validate-env.sh`'s `refuse_unsafe_backup_dir` (`/tmp/*` rejection)

### T2 — RED-first bash tests for refresh-frontend-deps CLI

- New file: `scripts/test-refresh-frontend-deps.sh` (165 LOC, executable)
- 4 scenarios: R5 (normal run prints + executes `docker compose up -d --force-recreate --renew-anon-volumes frontend`), R6 (`--dry-run` short-circuits, no docker exec), R7 (missing `docker` exits non-zero with missing-command message), R8 (unsupported flag `--skip-neo4j` exits 2 with usage; `-h|--help` exits 0)
- RED proven: test exits non-zero while `scripts/refresh-frontend-deps.sh` is absent

### T3 — GREEN: lockfile hash helpers in safe-rebuild

- Modified: `scripts/safe-rebuild.sh` (+~30 LOC)
- Added helpers before `SAFE_REBUILD_LIB_ONLY` early-return so tests can source them: `compute_frontend_lockfile_hash`, `frontend_lockfile_changed`, `maybe_renew_frontend_anonymous_volume`. Added `require_command sha256sum` to the main flow.
- Hash = `sha256sum frontend/pnpm-lock.yaml | awk '{print $1}'`; missing sentinel or diff = changed; missing lockfile fails clear.
- T1 helper tests GREEN; full-file test still RED (wiring not yet added)

### T4 — GREEN: wire renew into flow

- Modified: `scripts/safe-rebuild.sh` (+15/-5 LOC)
- Inserted `maybe_renew_frontend_anonymous_volume` between `docker compose build` and the post-build `docker compose up -d`. Sentinel `$BACKUP_DIR/frontend-pnpm-lock.sha256` is written only after a successful non-dry-run renew.
- Pre-backup `docker compose up -d --no-build postgres neo4j backend` path remains untouched.
- T1 end-to-end tests GREEN; `safe-rebuild.sh --dry-run` prints renew command but does not exec Docker.

### T5 — GREEN: implement refresh-frontend-deps

- New file: `scripts/refresh-frontend-deps.sh` (87 LOC, executable)
- `#!/bin/sh` + `set -eu`, `usage()`, `run()`, `require_command docker`, `compose()` wrapper. Only `--dry-run` and `-h|--help` accepted; anything else → usage on stderr + exit 2.
- Command shape exactly `docker compose up -d --force-recreate --renew-anon-volumes frontend`.
- This commit also shipped a small bug fix to `scripts/test-refresh-frontend-deps.sh`: the install-failure path used `grep "$LAST_OUT" pattern` (treating `$LAST_OUT` as a *filename*) instead of `printf '%s\n' "$LAST_OUT" | grep -q pattern`. POSIX `sh` has no `<<<` here-string. Bug discovered and fixed during T5 GREEN; kept TDD ordering intact by recording both in the T5 commit and noting it in the body.
- T2 CLI tests GREEN; `refresh-frontend-deps.sh --dry-run` prints and exits 0 without docker exec.

### T6 — `docs/backup-restore.md` callout

- Modified: `docs/backup-restore.md` (+18 LOC)
- Added a callout block near the existing "Do not run `docker compose down -v`" warning. Explicitly distinguishes data volumes (do not `docker volume rm`) from build-artifact anonymous volumes (renew with `scripts/refresh-frontend-deps.sh`).
- `grep -nE 'refresh-frontend-deps|build-artifact' docs/backup-restore.md` shows the new block.

### T7 — `README.md` troubleshooting pointer

- Modified: `README.md` (+10 LOC)
- Added a troubleshooting paragraph in the operator guidance region pointing to `scripts/refresh-frontend-deps.sh` as the safe recovery path after `pnpm-lock.yaml` changes.
- `grep -c 'refresh-frontend-deps' README.md` returns exactly 1.

### T8 — apply-phase CHANGELOG + final verification

- New content: `openspec/changes/renew-frontend-node-modules-volumes/tasks.md` (+26 LOC) — CHANGELOG table mapping T1-T8 to commits, plus a "Deviations from tasks.md" section.
- Final verification (all PASS):
  - `sh scripts/test-safe-rebuild-frontend-volume.sh` exits 0
  - `sh scripts/test-refresh-frontend-deps.sh` exits 0
  - `sh scripts/safe-rebuild.sh --dry-run` exits 0; renew command printed between build and final up
  - `sh scripts/refresh-frontend-deps.sh --dry-run` exits 0; command printed, no docker exec
  - `sh -n` for all four shell scripts: clean parse
  - `shellcheck` not installed (substituted with `sh -n`); flagged for verify phase
  - `git diff main..HEAD --stat`: 10 files, 1217 insertions (741 LOC implementation+docs, 476 LOC SDD artifacts); under the 800-line override

## Commits

1. `486fb07` `test(scripts): add RED-first bash tests for frontend volume renewal` (T1)
2. `560cb80` `test(scripts): add RED-first bash tests for refresh-frontend-deps CLI` (T2)
3. `f76aef6` `feat(scripts): add frontend lockfile hash helpers to safe-rebuild` (T3)
4. `7c39607` `feat(scripts): conditionally renew frontend anon volume in safe-rebuild` (T4)
5. `a790921` `feat(scripts): add refresh-frontend-deps operator recovery script` (T5)
6. `4910a79` `docs(backup-restore): clarify data-volume vs build-artifact volume recovery` (T6)
7. `8ee56de` `docs(readme): point operators to refresh-frontend-deps for stale deps` (T7)
8. `1cdb651` `chore(sdd): add apply-phase CHANGELOG to renew-frontend-node-modules-volumes tasks` (T8)

## Discoveries / Risks

1. **POSIX sh here-string gotcha**: `grep "$VAR" pattern` treats `$VAR` as a *filename*, not stdin content. Use `printf '%s\n' "$VAR" | grep -q pattern` instead. Caught at T5 GREEN and fixed in the same commit.
2. **`validate-env.sh --print-backup-dir` refuses `/tmp/*` BACKUP_DIR values** via `refuse_unsafe_backup_dir`. Sandbox end-to-end tests must NOT override `BACKUP_DIR`; instead let it resolve to a relative `.docker/backups` dir inside the sandbox.
3. **Stub-docker pattern for `docker compose ps -q <service>`**: `require_running_service` in `pre-rebuild-backup.sh` exits 1 when `ps -q` returns empty. The stub must print a non-empty fake container id for `compose ps -q *` so the test flow reaches the renew step.
4. **Sensitive-var placeholders**: copying `.env.example` to `.env` makes `validate-env.sh` reject the file because `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `NEO4J_PASSWORD` match their `.env.example` placeholders. Sandbox needs an explicit `.env` with production-safe non-placeholder values for these 3 keys.
5. **R4 "no destructive commands" check** must inspect only `docker.log` (executed commands) or lines starting with `+ ` (planned from `run()`), NOT the script's "Next verification" informational warning which mentions `docker compose down -v` / `docker volume rm` as a literal warning to operators.
6. **shellcheck not installed** in this sandbox; substituted with `sh -n` for all four touched shell scripts. Flagged for the verify phase in case stricter linting is required.
7. **T1 test size grew from ~170 LOC estimate to 408 LOC** because the sandbox+stub-docker pattern requires copying `.env.example`, `.env`, validate-env.sh, pre-rebuild-backup.sh, and the lockfile into each per-test sandbox, plus separate R1/R2/R3/R4 assertion blocks. Acceptable trade-off given the 800-line override.
8. **Test file uses `local`**: `scripts/test-safe-rebuild-frontend-volume.sh` uses `local` in test helper functions. Production scripts (`safe-rebuild.sh`, `refresh-frontend-deps.sh`) avoid `local` per project POSIX-`sh` convention; test files do not. Acceptable per project convention; flagged as a SUGGESTION in the verify report.

## Diff stats (vs main)

- `scripts/safe-rebuild.sh`: +53 LOC (helpers + wiring)
- `scripts/refresh-frontend-deps.sh`: +87 LOC (new)
- `scripts/test-safe-rebuild-frontend-volume.sh`: +408 LOC (new)
- `scripts/test-refresh-frontend-deps.sh`: +165 LOC (new)
- `docs/backup-restore.md`: +18 LOC
- `README.md`: +10 LOC
- **Implementation/docs subtotal**: 741 LOC (under 800-line override)
- `openspec/changes/renew-frontend-node-modules-volumes/{proposal,design,specs/.../spec,tasks}.md`: +476 LOC (SDD artifacts)
- **Total diff vs main**: 10 files, 1217 insertions
