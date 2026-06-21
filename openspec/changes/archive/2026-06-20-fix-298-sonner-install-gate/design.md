# Design: fix-298-sonner-install-gate

## 1. Approach summary

Implement the local frontend install gate as an additive docs-and-script change: a discoverable `frontend/README.md` covers Prerequisites / Install / Dev / Test / Build / Troubleshooting / Known gaps; root `README.md` gets a “Local frontend dev (no Docker)” subsection that points to it and explicitly distinguishes this path from Docker; `scripts/check-frontend-deps.sh` performs an opt-in bash pre-flight using `frontend/.frontend-deps-ok` as a SHA-256 lockfile sentinel and auto-recovers with `corepack pnpm install --frozen-lockfile` when the sentinel is stale or critical imports such as `sonner` are missing; `scripts/test-check-frontend-deps.sh` provides RED-first bash tests; `frontend/package.json` exposes `pnpm --dir frontend run check:deps` with no `predev` hook. Evidence is from `v1.13.2^{}`: pnpm pin at `frontend/package.json` L5, `sonner` at L28, auth import at `frontend/context/AuthContext.tsx` L2, Docker-only setup at `README.md` L61-L67, frontend test command at L88, lockfile sonner entries at L44/L1663/L3367, no `<Toaster />` in `frontend/App.tsx`, and no `frontend/README.md`. Single PR, branch from `v1.13.2`, forecast ~50-200 changed lines, no chained PRs.

## 2. File changes table

| File | Action | Description |
|---|---|---|
| `frontend/README.md` | New | Onboarding guide: Prerequisites, Install, Dev, Test, Build, Troubleshooting, Known gaps. |
| `README.md` | Modify | Add “Local frontend dev (no Docker)” subsection pointing to `frontend/README.md`. |
| `scripts/check-frontend-deps.sh` | New | Bash pre-flight: sentinel check + import check + install recovery. |
| `scripts/test-check-frontend-deps.sh` | New | RED-first bash tests for the pre-flight. |
| `frontend/package.json` | Modify | Add `"check:deps": "bash ../scripts/check-frontend-deps.sh"`. |

## 3. Implementation details

`scripts/check-frontend-deps.sh` uses `#!/usr/bin/env bash` and `set -euo pipefail`, derives `REPO_ROOT`, hashes `frontend/pnpm-lock.yaml`, compares it to `frontend/.frontend-deps-ok`, then scans only `frontend/context/AuthContext.tsx` and `frontend/App.tsx` for resolvable `from '...'` imports. If the sentinel is stale/missing or a tracked import lacks `frontend/node_modules/<pkg>`, it runs `(cd frontend && corepack pnpm install --frozen-lockfile)`, writes the current SHA-256 to the sentinel, and exits with the install result. Guard grep no-match paths with `|| true` or conditional grep to avoid `set -e` false failures.

| Decision | Choice | Rationale |
|---|---|---|
| Sentinel | SHA-256 of `pnpm-lock.yaml`, not mtime | Avoids drift when checkout/editor touches an unchanged lockfile. |
| Import scan | Only `AuthContext.tsx` + `App.tsx` | Exploration scoped the critical first-party resolvable imports; all-TSX scanning is over-engineering for #298. |
| Hooking | Manual `check:deps`, no `predev` | Keeps hot dev startup latency at zero and avoids surprise installs. |
| Sentinel location | `frontend/.frontend-deps-ok` | Close to the lockfile and avoids repo-root clutter. |

`scripts/test-check-frontend-deps.sh` follows the existing plain-shell test style from `scripts/test-safe-rebuild-path-validation.sh` but may use bash for arrays/shims. It creates `/tmp/` fixtures, copies the script plus tracked files, asserts side effects, and cleans up. Scenarios: recovery when `node_modules/sonner` is absent; no-op when sentinel matches and imports resolve; install failure via `PATH` shim returning non-zero. Commit 1 intentionally fails before the implementation script exists.

Docs: `frontend/README.md` includes Node 22/Corepack prerequisites, install via `corepack pnpm install --frozen-lockfile`, dev/test/build commands, troubleshooting for `Failed to resolve import "sonner"`, and known gaps: `<Toaster />` not mounted and Docker path unchanged. Root `README.md` addendum goes immediately after `Setup local`.

## 4. Worktree, branch, PR, commits

- Branch: `fix-298-sonner-install-gate`; worktree: `/home/alex/dev/next-gen/worktrees/fix-298-sonner-install-gate`; base: `git worktree add ... v1.13.2^{}`; PR base: `main`.
- PR title: `fix(frontend): add local-dev install gate and frontend README (#298)`; body closes #298, lists changed files and verification commands. Note: branch-pr skill normally requires `fix/<description>`; this cycle explicitly chooses the issue branch name from orchestration.

Reviewable commits:
1. `test(frontend): add RED-first bash tests for check-frontend-deps pre-flight` — only `scripts/test-check-frontend-deps.sh`, references #298, fails before script exists.
2. `feat(scripts): implement check-frontend-deps.sh pre-flight` — only implementation; makes tests pass.
3. `docs(frontend): add frontend README and root README local-dev pointer; wire check:deps pnpm script` — docs plus package script wiring.

This split preserves strict TDD: RED test-only, GREEN implementation-only, then orthogonal docs/wiring.

## 5. Pre-merge verification checklist

- `bash scripts/test-check-frontend-deps.sh`
- `corepack pnpm --dir frontend run check:deps`
- `corepack pnpm --dir frontend run test:run` (expect 57 files / 479 tests)
- `cat frontend/README.md` shows all 7 sections
- `grep -c "Local frontend dev (no Docker)" README.md` returns 1
- Diff against `v1.13.2` touches only the five planned files; backend, `.github/`, `frontend/context/`, and `frontend/App.tsx` diffs are empty.

## 6. Rollback plan

Revert the PR. No data, API, schema, telemetry, or backend impact. The pre-flight is opt-in through `check:deps`, so removal is safe.

## 7. Out of scope

CI workflow edits on `cicd/cd-lane`; `<Toaster />` mount; `sonner` version changes; auth import removal; backend changes; unrelated auth/session settings.

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---:|---|
| Sentinel drift | Low | Hash content, not mtime; still verify tracked imports. |
| Hand-rolled bash tests | Med | Mirror existing script-test style with explicit assertions. |
| Corepack disabled | Low | README states `corepack enable`; command fails loud. |
| `grep` no-match under `set -e` | Med | Use `|| true` or conditional grep. |
| Merge order with `cicd/cd-lane` | Med | Change is docs/script-only and independent. |

## 9. Open questions

None blocking. Sentinel format, two-file parsing scope, plain bash tests, single PR, and no `predev` hook are decided.
