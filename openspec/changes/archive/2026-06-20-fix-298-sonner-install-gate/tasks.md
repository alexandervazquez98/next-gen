# Tasks: fix-298-sonner-install-gate

- Status: Ready | Change: `fix-298-sonner-install-gate`
- Issue: `alexandervazquez98/next-gen#298` (`status:needs-review`)
- Branch/worktree: `fix-298-sonner-install-gate` @ `/home/alex/dev/next-gen/worktrees/fix-298-sonner-install-gate`
- Base: `v1.13.2^{}` (= `49dda73`) | PR base: `main` | Delivery: `single-pr` | Strict TDD: on

## Review Workload Forecast

- Estimated changed lines: 50-200
- Breakdown: `frontend/README.md` 40-80; `README.md` 5-15; `scripts/check-frontend-deps.sh` 20-40; `scripts/test-check-frontend-deps.sh` 30-60; `frontend/package.json` 1-3.

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## T1 — Worktree + clean baseline (no commit)

- [ ] 1.1 `git worktree add /home/alex/dev/next-gen/worktrees/fix-298-sonner-install-gate v1.13.2^{}`; `cd` in; `git status` clean; `git rev-parse HEAD` = `49dda73`; `corepack pnpm install --frozen-lockfile` in `frontend/`.
- [ ] 1.2 `corepack pnpm --dir frontend run test:run -v` → 57/479; capture for PR body.

## T2 — Commit 1: RED-first bash tests (`scripts/test-check-frontend-deps.sh`, new)

- [ ] 2.1 `test_check_deps_tests_recovery_path` — temp dir, tracked files + `package.json` stub, no `node_modules/sonner`; assert install ran, sentinel written, exit 0.
- [ ] 2.2 `test_check_deps_tests_no_op_sentinel_path` — valid sentinel (matching lockfile hash) + resolved imports; assert no install, sentinel unchanged, exit 0.
- [ ] 2.3 `test_check_deps_tests_install_failure_path` — shim `corepack` (NOT just `pnpm`) in `PATH` returning non-zero; assert exit non-zero, error printed, no sentinel.
- Verify all 3 FAIL (RED proven). Commit: `test(frontend): add RED-first bash tests for check-frontend-deps pre-flight`.

## T3 — Commit 2: GREEN implementation (`scripts/check-frontend-deps.sh`, new)

- [ ] 3.1 `#!/usr/bin/env bash` + `set -euo pipefail`; derive `REPO_ROOT`; SHA-256 of `frontend/pnpm-lock.yaml` vs `frontend/.frontend-deps-ok` sentinel; chmod +x.
- [ ] 3.2 Scan `AuthContext.tsx` + `App.tsx` for `from '...'` imports via `for`/`grep -oE`+`sed -E`; skip relative (`./`, `../`); wrap grep in `|| true` for `set -e` safety.
- [ ] 3.3 On miss: `(cd frontend && corepack pnpm install --frozen-lockfile)`; rewrite sentinel; exit with install result.
- Verify T2 GREEN; `check:deps` end-to-end; manual sentinel flow. Commit: `feat(scripts): implement check-frontend-deps.sh pre-flight`.

## T4 — Commit 3: docs + pnpm wiring

- Files: `frontend/README.md` (new), `README.md` (modify), `frontend/package.json` (modify).
- [ ] 4.1 Create `frontend/README.md` with 7 sections (Prerequisites, Install, Dev, Test, Build, Troubleshooting, Known gaps); install uses `corepack pnpm install --frozen-lockfile`; mention `corepack enable`; Known gaps lists absent `<Toaster />`.
- [ ] 4.2 Insert "Local frontend dev (no Docker)" in `README.md` AFTER L67; must not shift L88.
- [ ] 4.3 `frontend/package.json`: add `"check:deps": "bash ../scripts/check-frontend-deps.sh"` to `scripts`. No `predev`.
- Verify 7 `## Section` greps; 1 hit "Local frontend dev (no Docker)"; 1 hit `"check:deps"`; `test:run` still 57/479. Commit: `docs(frontend): add frontend README and root README local-dev pointer; wire check:deps pnpm script`.

## T5 — Final verification + diff scope check

- [ ] 5.1 `git diff v1.13.2..HEAD --stat` — only 5 in-scope files.
- [ ] 5.2 `git diff v1.13.2..HEAD -- backend/ .github/ frontend/context/ frontend/App.tsx` must be empty.
- [ ] 5.3 Full diff of 5 scoped files; should match ~50-200 line forecast.
- [ ] 5.4 `corepack pnpm --dir frontend run test:run` — final regression check.

## Hard constraints

- DO NOT modify `backend/`, `frontend/context/`, `frontend/App.tsx`, `.github/`, or `openspec/changes/ci-cd-pipeline/exploration.md` (separate stream).
- `frontend/package.json`: scripts block only. Never change `stale_rotation_max_recoveries` or unrelated auth/session settings.
- Use `v1.13.2^{}` for base-SHA. No `Co-Authored-By` trailers. Commit bodies explain WHY.
- Strict TDD: T2 (RED) precedes T3 (GREEN).
