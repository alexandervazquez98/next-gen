# Archive Report — renew-frontend-node-modules-volumes

## Status

PASS WITH WARNINGS (verdict lifted from `verify-report.md`; no CRITICAL findings; all R1-R8 requirements PASS with runtime coverage)

## Archive date

2026-06-21

## Branch SHA at archive

`1cdb651541282b9e81095fa8480eae70200fa684` — `chore(sdd): add apply-phase CHANGELOG to renew-frontend-node-modules-volumes tasks` (T8 SDD commit)

## Main SHA at archive

NOT YET MERGED. Branch `fix/306-renew-frontend-node-modules-volumes` is ready for review; PR to be opened and merged by user or next session. The cycle base on `main` was `aa852a8` (last main commit before the branch diverged).

## Issue

`alexandervazquez98/next-gen#306` — `fix(frontend): renew dev frontend node_modules volume when pnpm-lock.yaml changes`

## Linked PR

NOT YET OPENED. Branch `fix/306-renew-frontend-node-modules-volumes` is ready for review at commit `1cdb651`; PR to be opened by user or next session. Once the PR is opened, the URL will be added to the canonical spec's `## Source` section.

## Change ID

`renew-frontend-node-modules-volumes`

## New capability created

`frontend-dependency-volume-renewal` — `openspec/specs/frontend-dependency-volume-renewal/spec.md` (8 Requirements / 8 Scenarios, source-of-truth going forward)

Delta spec mirrored for traceability at `openspec/changes/archive/2026-06-21-renew-frontend-node-modules-volumes/specs/frontend-dependency-volume-renewal/spec.md`.

## Modified capabilities

None.

## Out-of-scope items deferred

The 6 explicit non-goals from `proposal.md` (and reaffirmed in `design.md`):

1. Do not remove the anonymous `/app/node_modules` volume from `docker-compose.yml`. The anonymous volume is intentional for dev hot reload; this change adds renewal behavior, not removal.
2. Do not add destructive cleanup commands (`docker compose down -v`, `docker volume rm`). The capability explicitly forbids these in any safe-rebuild path; renewal is scoped to `--renew-anon-volumes frontend` only.
3. Do not change production `frontend-prod` compose behavior. `frontend-prod` has no anonymous volume; renewal would be a no-op there.
4. Do not change CD triggers or deployment automation in `.github/workflows/cd.yml`. Auto-deploy is already disabled; this change does not alter CD flow.
5. Do not broaden recovery into general operations documentation (no `scripts/README.md` or `docs/operations.md`). Use existing homes: `docs/backup-restore.md` and `README.md`.
6. Do not add `--pull` to `docker compose build`; do not add a `safe-rebuild.sh --renew-frontend-anon-volumes` flag. Manual recovery belongs in the dedicated `scripts/refresh-frontend-deps.sh`.

## Risks accepted (from `verify-report.md`)

| Risk | Severity | Mitigation in code | Residual exposure |
|---|---|---|---|
| `shellcheck` not installed in this sandbox | WARNING | `sh -n` parse check substituted for all four changed shell scripts (passes). | If a CI host enforces `shellcheck`, re-run lint before merge. SUGGESTION: install `shellcheck` in CI; project does not currently gate on it. |
| Valid `.env` is a dry-run smoke precondition | WARNING | `.env.example` placeholders (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `NEO4J_PASSWORD`) are rejected by `validate-env.sh`; sandbox test must produce a non-placeholder `.env`. | An operator without a valid `.env` cannot dry-run `safe-rebuild.sh`. Acceptable per operator deploy contract. SUGGESTION: document a verification fixture or one-shot `.env` prep script. |
| Test helpers use non-POSIX `local` | WARNING | Production scripts (`safe-rebuild.sh`, `refresh-frontend-deps.sh`) avoid `local` per project convention. Test files use `local` in helper functions. | If strict POSIX portability for tests is required, replace `local` in `scripts/test-safe-rebuild-frontend-volume.sh` and `scripts/test-refresh-frontend-deps.sh`. SUGGESTION only. |
| Destructive command strings appear in operator advisory text | WARNING | `docker compose down -v` and `docker volume rm` appear only in the `safe-rebuild.sh` "Next verification" advisory warning to operators, NOT as `+ ` planned commands or in `docker.log`. Verified by parse check. | Risk is that the literal strings could trigger a naive `grep` alarm. Documented in verify report; tests use `^+\|docker.log` scoping to avoid false positives. |

## Commits

1. `486fb07` — `test(scripts): add RED-first bash tests for frontend volume renewal` (T1 RED)
2. `560cb80` — `test(scripts): add RED-first bash tests for refresh-frontend-deps CLI` (T2 RED)
3. `f76aef6` — `feat(scripts): add frontend lockfile hash helpers to safe-rebuild` (T3 GREEN helpers)
4. `7c39607` — `feat(scripts): conditionally renew frontend anon volume in safe-rebuild` (T4 GREEN wiring)
5. `a790921` — `feat(scripts): add refresh-frontend-deps operator recovery script` (T5 GREEN refresh; bundles one test-bug fix)
6. `4910a79` — `docs(backup-restore): clarify data-volume vs build-artifact volume recovery` (T6 DOCS)
7. `8ee56de` — `docs(readme): point operators to refresh-frontend-deps for stale deps` (T7 DOCS)
8. `1cdb651` — `chore(sdd): add apply-phase CHANGELOG to renew-frontend-node-modules-volumes tasks` (T8 SDD)

## Lessons learned

- **POSIX `sh` here-string gotcha surfaces in real bash tests.** `grep "$VAR" pattern` treats `$VAR` as a *filename*, not stdin. POSIX `sh` has no `<<<` here-string; the correct idiom is `printf '%s\n' "$VAR" | grep -q pattern`. Caught at T5 GREEN and fixed in the same commit (the install-failure path in `scripts/test-refresh-frontend-deps.sh`). When a TDD test fails in an unexpected way, suspect the test's shell syntax first.

- **`validate-env.sh --print-backup-dir` refuses `/tmp/*` via `refuse_unsafe_backup_dir`.** Sandbox-style end-to-end bash tests for `safe-rebuild.sh` must NOT override `BACKUP_DIR`; let it resolve to a relative `.docker/backups` dir inside the per-test sandbox. This constraint inflated T1's test size from ~170 LOC to 408 LOC. Forecast that bash harness size grows when sandbox invariants apply, not just scenario count.

- **Stub-docker pattern requires non-empty `compose ps -q *` output.** `require_running_service` in `pre-rebuild-backup.sh` exits 1 if `docker compose ps -q <service>` returns empty. A naive stub `docker` that prints nothing breaks the flow before the renew step. The fix is to print a fake container id for `compose ps -q *` calls.

- **`.env` copy from `.env.example` fails `validate-env.sh` on placeholder secrets.** Three keys (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `NEO4J_PASSWORD`) are checked against their `.env.example` placeholders and rejected. Sandbox tests must produce a fresh `.env` with non-placeholder values for these keys. Documented for future SDD apply cycles that need safe-rebuild sandbox tests.

- **R4 "no destructive commands" check must scope its grep.** Inspecting the entire `safe-rebuild.sh` script will surface the operator advisory warning that mentions `docker compose down -v` and `docker volume rm` literally. The R4 guard is about *executed* or *planned* commands: inspect only `docker.log` (executed) or lines starting with `+ ` (planned from `run()`). Documenting the test scoping rules in the spec would prevent future verify runs from re-discovering this gotcha.

- **shellcheck absence forced `sh -n` substitution.** This sandbox has no `shellcheck` (`exit 127`); the project does not currently enforce shell lint in CI. `sh -n` is a parse-only check that catches syntax but not lint-level issues (unused vars, word-splitting, quoting). Acceptable for this cycle; flagged so a future cycle can introduce a `shellcheck` job if the team wants stricter shell review.

- **T5 commit bundled a test bug fix.** The T5 commit (`a790921`) shipped both the `scripts/refresh-frontend-deps.sh` implementation AND a one-line fix in `scripts/test-refresh-frontend-deps.sh` (the here-string bug above). Strict-TDD purists may want this split into two commits; we kept it together because the bug was discovered during T5 GREEN and was blocking T5's own acceptance. The commit body explicitly calls this out. Lesson: when a test bug blocks a GREEN step, the test-fix and the implementation can share a commit as long as the commit body is honest about the bundle.

- **SDD artifacts land in the CHANGELOG commit, not separately.** All four SDD artifacts (`proposal.md`, `design.md`, `specs/.../spec.md`, `tasks.md`) were added in commit `1cdb651` (T8). This is acceptable because the SDD artifacts are documentation, not code under TDD. The fix-298 cycle used the same pattern. If the team ever wants stricter TDD for SDD artifacts, the prop/spec/design phases would land as separate commits before any apply work.

## Relevant files

- `openspec/specs/frontend-dependency-volume-renewal/spec.md` — consolidated capability spec (source of truth going forward)
- `openspec/changes/archive/2026-06-21-renew-frontend-node-modules-volumes/` — full audit trail (proposal, design, tasks, verify-report, apply-progress, delta spec, archive-report)
- `scripts/safe-rebuild.sh` — POSIX-`sh` rebuild script with new lockfile hash helpers + frontend-scoped renew wiring
- `scripts/refresh-frontend-deps.sh` — single-purpose operator recovery CLI (`--dry-run`, `-h|--help`)
- `scripts/test-safe-rebuild-frontend-volume.sh` — RED-first end-to-end tests for R1-R4 (sandbox with stub Docker)
- `scripts/test-refresh-frontend-deps.sh` — RED-first CLI tests for R5-R8
- `docs/backup-restore.md` — data-volume vs build-artifact-volume callout with `refresh-frontend-deps.sh` pointer
- `README.md` — troubleshooting paragraph for stale `node_modules` in Docker dev path

## Cycle stats

- 8 SDD phases (explore → propose → spec → design → tasks → apply → verify → archive)
- 2 re-runs in verify phase (first pass failed on missing `.env` for safe-rebuild dry-run and missing apply-progress TDD table; second pass fixed `.env` and added TDD table)
- 8 commits on branch `fix/306-renew-frontend-node-modules-volumes`
- 1217 insertions total diff vs `main` (741 LOC implementation+docs, 476 LOC SDD artifacts)
- Under 800-line implementation/docs review budget by 59 lines
- Branch ready for review; PR to be opened by user or next session
