# Proposal: fix-298-sonner-install-gate

Status: Draft  
Change ID: `fix-298-sonner-install-gate`  
GitHub Issue: `alexandervazquez98/next-gen#298` (`status:needs-review`)  
Extends: none  
Upstream: PR #291 `fix(auth): local-only frontend idle logout with sonner toast (#287 PR2)`, commit `fb75972`

## Intent

When a developer clones the repo and runs `pnpm dev` outside Docker without first running `corepack pnpm install --frozen-lockfile`, Vite fails with `[plugin:vite:import-analysis] Failed to resolve import "sonner" from "context/AuthContext.tsx"`. The `sonner` dependency was added by the #287 PR2 chain; the install step is undocumented for non-Docker local dev and there is no pre-flight to auto-recover. This change closes the local-dev onboarding gap. CI install gates are already in flight via the parallel `ci-cd-pipeline` chain on `cicd/cd-lane` and are out of scope here.

## Scope

### In Scope
- Single PR under the 400-line review budget.
- New `frontend/README.md`: prerequisites, install, dev, test, build, troubleshooting, and known gaps.
- Root `README.md` addendum: short “Local frontend dev (no Docker)” subsection pointing to `frontend/README.md`; keep Docker setup untouched.
- New executable `scripts/check-frontend-deps.sh`: cheap sentinel/hash pre-flight that detects missing frontend imports and runs `corepack pnpm install --frozen-lockfile` when needed.
- New `scripts/test-check-frontend-deps.sh`: RED-first bash tests for missing dependency recovery, no-op sentinel path, and install failure.
- `frontend/package.json` script: `check:deps` invokes `bash ../scripts/check-frontend-deps.sh`; no `predev` hook.

### Out of Scope
- CI workflow edits (`frontend-ci.yml`, `smoke.yml`, `lint.yml`); already handled on `cicd/cd-lane`.
- Mounting `<Toaster />` in `frontend/App.tsx`; separate child issue.
- Changing `sonner` version `2.0.7`, removing the auth import, backend changes, or unrelated auth/session settings.

## Capabilities

### New Capabilities
- `frontend-local-dev-install-gate`: a developer running frontend dev/build/test directly against a fresh checkout must not be left with Vite import-analysis errors for declared dependencies; docs and/or an opt-in pre-flight provide recovery.

### Modified Capabilities
- None.

## Verified Current Evidence

- `v1.13.2` (= `49dda73`, the released tag this cycle branches from): `frontend/package.json` L5 pins `pnpm@10.12.1`; L28 declares `"sonner": "2.0.7"`.
- `v1.13.2`: `frontend/context/AuthContext.tsx` L2 imports `toast` from `sonner`.
- `v1.13.2`: `frontend/pnpm-lock.yaml` has `sonner` entries at L44, L1663, L3367.
- `v1.13.2`: root `README.md` L61-L64 documents Docker setup only; L88 shows the focused frontend test command (`corepack pnpm --dir frontend run test:run -- ...`) which assumes install already happened.
- `v1.13.2`: `frontend/README.md` does not exist; `frontend/App.tsx` has no `Toaster` import/mount.
- Exploration reproduced the exact issue by removing `frontend/node_modules/sonner`; `pnpm install --frozen-lockfile` recovered; current frontend suite is 57 files / 479 tests.

## Approach

Use Approach A from exploration: onboarding docs plus an opt-in, RED-tested pre-flight script exposed as `pnpm --dir frontend run check:deps`. The sentinel SHOULD store the SHA-256 of `frontend/pnpm-lock.yaml` in `frontend/.frontend-deps-ok` and still verify critical imports such as `sonner`; this avoids stale sentinel drift without adding `predev` latency.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `frontend/README.md` | New | Non-Docker frontend onboarding and known gaps. |
| `README.md` | Modified | Pointer to frontend local-dev path. |
| `scripts/check-frontend-deps.sh` | New | Dependency pre-flight/recovery. |
| `scripts/test-check-frontend-deps.sh` | New | Bash tests for the pre-flight. |
| `frontend/package.json` | Modified | Adds `check:deps`. |

## Acceptance Criteria

- [ ] `frontend/README.md` has `## Prerequisites`, `## Install`, `## Dev`, `## Test`, `## Build`, `## Troubleshooting`, and `## Known gaps`; install uses `corepack pnpm install --frozen-lockfile`.
- [ ] Root `README.md` has “Local frontend dev (no Docker)” and says this path is NOT covered by `docker-compose up`.
- [ ] `scripts/check-frontend-deps.sh` is executable, idempotent, checks missing imports from `frontend/context/AuthContext.tsx` and `frontend/App.tsx`, installs on miss, exits non-zero on install failure, and prints clear success/failure messages.
- [ ] `scripts/test-check-frontend-deps.sh` is written RED-first and passes for recovery, no-op sentinel, and mocked install failure.
- [ ] `pnpm --dir frontend run check:deps` works.
- [ ] `pnpm --dir frontend run test:run` still passes: 57 files / 479 tests.
- [ ] Merge order is non-blocking: if `cicd/cd-lane` lands first, this PR adds docs/script only; if this PR lands first, CI gates arrive later with the chain.

## Risks

| Risk | Likelihood | Mitigation |
|---|---:|---|
| `cicd/cd-lane` takes weeks to merge, so main CI lacks frontend install gates temporarily. | Med | Do not block; local pre-flight is independently useful. |
| `predev` latency surprises developers. | Med | No `predev`; manual `check:deps` script only. |
| Sentinel drift masks missing deps. | Med | Store lockfile hash and verify critical imports. |
| `<Toaster />` follow-up is missed. | Low | Surface it in README Known gaps and related artifacts. |

## Rollback Plan

Revert the PR. No data, API, schema, or backend impact. The pre-flight is opt-in through `check:deps`, so removal is safe.

## Dependencies

- Corepack honoring `pnpm@10.12.1`.
- Bash for scripts/tests.
- pnpm install access to the lockfile-defined dependency graph.

## Open Questions Before Spec

- Sentinel format: recommend `frontend/.frontend-deps-ok` containing the lockfile SHA-256.
- Parsing scope: recommend only `frontend/context/AuthContext.tsx` and `frontend/App.tsx`; all-TSX scanning is over-engineering for this bug.
- Test framework: recommend plain bash with `set -euo pipefail`, matching existing project script tests.
