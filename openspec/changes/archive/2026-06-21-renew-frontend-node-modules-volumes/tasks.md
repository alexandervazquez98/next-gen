# Tasks: renew-frontend-node-modules-volumes

- Change: `renew-frontend-node-modules-volumes` | Issue: `alexandervazquez98/next-gen#306`
- Capability: `frontend-dependency-volume-renewal` (R1-R8) | TDD: `strict` | Delivery: `single-pr` | Budget: 800 LOC

## Review Workload Forecast

| Metric | Value |
|---|---|
| Estimated changed lines | ~580 |
| 800-line budget risk | Low |
| Chained PRs recommended | No |
| Decision needed before apply | No |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
800-line budget risk: Low

> Single-PR forecast: 8 files, ~580 LOC, no source-code change outside `scripts/`, `docs/`, `README.md`. Stays well under the 800-line override; no chained PR needed.

## T1 — RED tests for safe-rebuild frontend volume

- Reqs: R1, R2, R3, R4 | Phase: RED
- Files: `scripts/test-safe-rebuild-frontend-volume.sh` (new, ~170 LOC)
- Verify: `sh scripts/test-safe-rebuild-frontend-volume.sh` exits non-zero with "function not defined" / "not found"
- Commit: `test(scripts): add RED-first bash tests for frontend volume renewal`
- Acceptance: helper tests for `compute_frontend_lockfile_hash`, `frontend_lockfile_changed`, `maybe_renew_frontend_anonymous_volume` + end-to-end tests for R1 (unchanged → no `--renew-anon-volumes`), R2 (changed → exactly that command scoped to `frontend`), R3 (`--dry-run` prints but no docker exec), R4 (no `docker compose down -v` and no `docker volume rm` in recorded log). All FAIL because helpers/script-change do not exist yet. Stub `docker` via fake `PATH`.

## T2 — RED tests for refresh-frontend-deps.sh CLI

- Reqs: R5, R6, R7, R8 | Phase: RED
- Files: `scripts/test-refresh-frontend-deps.sh` (new, ~130 LOC)
- Verify: `sh scripts/test-refresh-frontend-deps.sh` exits non-zero (script not found)
- Commit: `test(scripts): add RED-first bash tests for refresh-frontend-deps CLI`
- Acceptance: tests for R5 (normal command shape, `+ docker compose up -d --force-recreate --renew-anon-volumes frontend`), R6 (`--dry-run` prints + no docker exec), R7 (missing `docker` exits non-zero with missing-command message), R8 (unsupported flag `--skip-neo4j` exits 2 with usage, no docker exec; `-h|--help` exits 0). All FAIL until T5 lands.

## T3 — GREEN: lockfile hash helpers in safe-rebuild.sh

- Reqs: R1, R2 (helper level) | Phase: GREEN
- Files: `scripts/safe-rebuild.sh` (+~30 LOC): add `compute_frontend_lockfile_hash`, `frontend_lockfile_changed`, and `require_command sha256sum` call. Helpers placed BEFORE the `SAFE_REBUILD_LIB_ONLY` early-return so tests can source them.
- Verify: `sh scripts/test-safe-rebuild-frontend-volume.sh` passes the 3 helper tests; full file still exits non-zero (wiring tests T4 still fail).
- Commit: `feat(scripts): add frontend lockfile hash helpers to safe-rebuild`
- Acceptance: hash = `sha256sum frontend/pnpm-lock.yaml | awk '{print $1}'`; missing sentinel or diff = changed; missing lockfile fails clear; helpers sourceable via `SAFE_REBUILD_LIB_ONLY=1`.

## T4 — GREEN: wire `maybe_renew_frontend_anonymous_volume` into flow

- Reqs: R2, R3, R4 | Phase: GREEN
- Files: `scripts/safe-rebuild.sh` (+~15 / -5 LOC): insert `maybe_renew_frontend_anonymous_volume` between current L205 (`docker compose build`) and L206 (`docker compose up -d`); write `$BACKUP_DIR/frontend-pnpm-lock.sha256` ONLY after a successful non-dry-run renew. Pre-backup mount path at L188 (`docker compose up -d --no-build postgres neo4j backend`) stays untouched.
- Verify: `sh scripts/test-safe-rebuild-frontend-volume.sh` exits zero; `sh scripts/safe-rebuild.sh --dry-run` prints renew command but does not exec docker.
- Commit: `feat(scripts): conditionally renew frontend anon volume in safe-rebuild`
- Acceptance: T1 end-to-end tests GREEN; renew scoped to `frontend` (final arg asserted); no destructive commands in any path; sentinel write gated on successful renew.

## T5 — GREEN: implement `scripts/refresh-frontend-deps.sh`

- Reqs: R5, R6, R7, R8 | Phase: GREEN
- Files: `scripts/refresh-frontend-deps.sh` (new, ~65 LOC)
- Verify: `sh scripts/test-refresh-frontend-deps.sh` exits zero; manual smoke `sh scripts/refresh-frontend-deps.sh --dry-run` prints `+ docker compose up -d --force-recreate --renew-anon-volumes frontend` and exits 0 without docker exec.
- Commit: `feat(scripts): add refresh-frontend-deps operator recovery script`
- Acceptance: `#!/bin/sh` + `set -eu`, `usage()`, `run()`, `require_command docker`, `compose()` wrapper per project convention. Only `--dry-run` and `-h|--help` accepted; anything else → usage on stderr + exit 2. Command shape exactly `docker compose up -d --force-recreate --renew-anon-volumes frontend`.

## T6 — `docs/backup-restore.md` callout

- Reqs: docs (R4 risk + recovery pointer) | Phase: DOCS
- Files: `docs/backup-restore.md` (+~35 LOC) — callout box near existing "Do not run `docker compose down -v`" warning (~L13).
- Verify: `grep -nE 'refresh-frontend-deps|build-artifact' docs/backup-restore.md` shows the new block.
- Commit: `docs(backup-restore): clarify data-volume vs build-artifact volume recovery`
- Acceptance: explicit warning against `docker volume rm`; pointers to `scripts/refresh-frontend-deps.sh` for stale `node_modules`; does NOT recommend `docker compose down -v`.

## T7 — `README.md` troubleshooting pointer

- Reqs: docs (operator visibility) | Phase: DOCS
- Files: `README.md` (+~15 LOC) — troubleshooting paragraph (~L106-112 region).
- Verify: `grep -n 'refresh-frontend-deps' README.md` returns exactly one hit.
- Commit: `docs(readme): point operators to refresh-frontend-deps for stale deps`
- Acceptance: single paragraph mentioning `refresh-frontend-deps.sh` as the safe recovery path after `pnpm-lock.yaml` changes; no destructive advice.

## T8 — final verification + repo-wide sanity

- Phase: VERIFY (no commit)
- Verify (all must pass):
  1. `sh scripts/safe-rebuild.sh --dry-run` exits zero
  2. `sh scripts/test-safe-rebuild-frontend-volume.sh` exits zero
  3. `sh scripts/test-refresh-frontend-deps.sh` exits zero
  4. `shellcheck scripts/safe-rebuild.sh scripts/refresh-frontend-deps.sh scripts/test-safe-rebuild-frontend-volume.sh scripts/test-refresh-frontend-deps.sh` no warnings
  5. `git diff --stat <base>...HEAD` ≤ 800 LOC across the 8 files only
- Acceptance: PR ready. `git log` proves strict TDD: T1 + T2 commits precede T3 + T4 + T5.

## Hard constraints

- DO NOT modify `backend/`, `frontend/context/`, `frontend/App.tsx`, `frontend/Dockerfile*`, `docker-compose*.yml`, `.github/`.
- DO NOT add `--pull` to `docker compose build`; DO NOT add a `--renew-frontend-anon-volumes` flag to `safe-rebuild.sh` (manual recovery belongs in `scripts/refresh-frontend-deps.sh`).
- Sentinel `$BACKUP_DIR/frontend-pnpm-lock.sha256` written ONLY after successful non-dry-run renew.
- `--renew-anon-volumes` ALWAYS scoped to `frontend`; tests assert the final arg is `frontend`.
- Pre-backup mount path at L188 (`docker compose up -d --no-build postgres neo4j backend`) MUST stay untouched.
- Strict TDD: T1 and T2 commits land BEFORE T3/T4/T5. Each test commit precedes its implementation commit in `git log`.

## Commit map (work-unit-commits)

| # | Task | Commit message | Work unit |
|---|---|---|---|
| 1 | T1 | `test(scripts): add RED-first bash tests for frontend volume renewal` | RED tests for safe-rebuild wiring |
| 2 | T2 | `test(scripts): add RED-first bash tests for refresh-frontend-deps CLI` | RED tests for refresh script |
| 3 | T3 | `feat(scripts): add frontend lockfile hash helpers to safe-rebuild` | Helpers |
| 4 | T4 | `feat(scripts): conditionally renew frontend anon volume in safe-rebuild` | Wiring |
| 5 | T5 | `feat(scripts): add refresh-frontend-deps operator recovery script` | Refresh script impl |
| 6 | T6 | `docs(backup-restore): clarify data-volume vs build-artifact volume recovery` | Backup-restore docs |
| 7 | T7 | `docs(readme): point operators to refresh-frontend-deps for stale deps` | README docs |
| 8 | T8 | (verification only — no commit) | PR-ready check |

## CHANGELOG (apply phase)

Actual commits landed on `fix/306-renew-frontend-node-modules-volumes`:

| # | Task | Commit SHA | Subject |
|---|---|---|---|
| 1 | T1 | `486fb07` | test(scripts): add RED-first bash tests for frontend volume renewal |
| 2 | T2 | `560cb80` | test(scripts): add RED-first bash tests for refresh-frontend-deps CLI |
| 3 | T3 | `f76aef6` | feat(scripts): add frontend lockfile hash helpers to safe-rebuild |
| 4 | T4 | `7c39607` | feat(scripts): conditionally renew frontend anon volume in safe-rebuild |
| 5 | T5 | `a790921` | feat(scripts): add refresh-frontend-deps operator recovery script |
| 6 | T6 | `4910a79` | docs(backup-restore): clarify data-volume vs build-artifact volume recovery |
| 7 | T7 | `8ee56de` | docs(readme): point operators to refresh-frontend-deps for stale deps |
| 8 | T8 | (no commit) | all 9 + 8 = 17 tests pass; `sh -n` clean; 741 LOC under 800-line budget |

### Deviations from tasks.md

- **T1 test size**: spec estimated ~170 LOC; actual 408 LOC. The increase is driven by a sandbox-with-stub-docker pattern that copies `.env.example`, `.env`, and the helper scripts into a per-test temp dir, plus end-to-end R1/R2/R3/R4 assertions. This was needed because `validate-env.sh` refuses unsafe `BACKUP_DIR` values like `/tmp/*` and the script needs a valid `.env` to reach the renew step in a sandbox.
- **T2 test size**: spec estimated ~130 LOC; actual 165 LOC. The extra ~35 LOC covers the missing-docker path (R7) which required a `sh` symlink in the empty PATH dir to avoid breaking the script's interpreter, plus the help/unsupported-flag negative cases.
- **T5 fix-up commit**: the same commit (`a790921`) shipped both `scripts/refresh-frontend-deps.sh` and a small bug fix in `scripts/test-refresh-frontend-deps.sh`. The test bug was that `grep` was called with `$LAST_OUT` as a *filename* argument instead of piped through stdin; POSIX `sh` has no `<<<` here-string. Fixed by switching to `printf '%s\n' "$LAST_OUT" | grep -q ...`. Bundled into the T5 commit because the bug was discovered during T5 GREEN and blocking T5's own acceptance; kept TDD ordering intact by not amending T5 but explicitly noting it in the commit body.
- **shellcheck not available** in this sandbox (T8 step 4). Substituted with `sh -n` for all four touched scripts, which is the project-standard `sh` parse check; flagged for the verify phase if a stricter lint is required.

### Strict-TDD proof

`git log --oneline aa852a8..HEAD` shows the two `test(scripts):` commits (`486fb07`, `560cb80`) preceding all three `feat(scripts):` commits (`f76aef6`, `7c39607`, `a790921`), satisfying the spec's "T1 + T2 commits precede T3 + T4 + T5 in git log" invariant.
