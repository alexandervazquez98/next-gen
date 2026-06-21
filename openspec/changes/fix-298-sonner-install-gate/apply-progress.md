# Apply Progress — fix-298-sonner-install-gate

- Change: `fix-298-sonner-install-gate`
- Cycle base SHA: `49dda73` (= `v1.13.2^{}`) — verified at T1.
- Branch / worktree: `fix-298-sonner-install-gate` @ `/home/alex/dev/next-gen/worktrees/fix-298-sonner-install-gate`
- Strict TDD: ON
- Mode: auto (single PR; size-exception since forecast 50-200 < 400)

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| T2 — RED tests | `scripts/test-check-frontend-deps.sh` | Bash (3 scenarios) | N/A (new) | ✅ 3/3 RED | ➖ N/A | ➖ N/A (each test is a separate scenario) | ➖ None needed |
| T3 — GREEN impl | (same test file) | Bash | N/A | ➖ N/A | ✅ 3/3 GREEN | ➖ N/A | ✅ Bash param-strip + word-split bug fixed |
| T4 — Docs + wiring | N/A (no test) | N/A | 57/479 baseline | ➖ N/A | ➖ N/A | ➖ N/A | ➖ None needed |

## Completed Tasks

### T1 — Worktree + baseline
- `git worktree add ... v1.13.2^{}` → worktree at `/home/alex/dev/next-gen/worktrees/fix-298-sonner-install-gate`
- `git rev-parse HEAD` = `49dda73` ✅
- Branch `fix-298-sonner-install-gate` created from v1.13.2
- `corepack pnpm install --frozen-lockfile` (frontend/) → `Done in 1.5s using pnpm v10.12.1`
- Baseline test run: **57 test files passed / 479 tests passed**

### T2 — RED-first bash tests
- New file: `scripts/test-check-frontend-deps.sh` (executable)
- 3 RED scenarios: recovery, no-op sentinel, install failure
- RED proven: 0/3 passed (script under test missing)
- Commit `fc9d351` — `test(frontend): add RED-first bash tests for check-frontend-deps pre-flight`

### T3 — GREEN implementation
- New file: `scripts/check-frontend-deps.sh` (executable, 114 lines)
- Implementation: SHA-256 lockfile hash + sentinel + 2-file import scan + `corepack pnpm install --frozen-lockfile` recovery
- GREEN proven: 3/3 passed
- Manual end-to-end: rm sentinel → script runs install + writes sentinel → second run is no-op
- Commit `d3f74b9` — `feat(scripts): implement check-frontend-deps.sh pre-flight`

### T4 — Docs + pnpm wiring
- New file: `frontend/README.md` (7 sections: Prerequisites, Install, Dev, Test, Build, Troubleshooting, Known gaps)
- Modified: `README.md` — added `## Local frontend dev (no Docker)` section AFTER `## Tests focalizados` (does NOT shift v1.13.2 L88 content; test command preserved verbatim).
- Modified: `frontend/package.json` — added `"check:deps": "bash ../scripts/check-frontend-deps.sh"` to scripts block (alphabetical position between `build` and `dev`; reordered `build`/`dev` and `test:run`/`test:coverage` into alphabetical order — minimal scope creep, no settings touched).
- Verification:
  - `grep -cE '^## (Prerequisites|Install|Dev|Test|Build|Troubleshooting|Known gaps)$' frontend/README.md` → **7** ✅
  - `grep -c 'Local frontend dev (no Docker)' README.md` → **1** ✅
  - `grep '"check:deps"' frontend/package.json` → **1** match ✅
  - `grep -F 'corepack pnpm --dir frontend run test:run -- hooks/queries/resourceQueries.test.tsx components/__tests__/EventDetailModal.acceptance.test.tsx' README.md` → preserves v1.13.2 L88 content ✅
  - `cd frontend && corepack pnpm run test:run` → **57 files / 479 tests passed** (no regressions) ✅
  - `cd frontend && corepack pnpm run check:deps` → end-to-end works (install runs, sentinel written, second run is no-op) ✅

### T5 — Final verification — PENDING

## Commits

1. `fc9d351` `test(frontend): add RED-first bash tests for check-frontend-deps pre-flight` (T2)
2. `d3f74b9` `feat(scripts): implement check-frontend-deps.sh pre-flight` (T3)
3. `<T4 commit>` `docs(frontend): add frontend README and root README local-dev pointer; wire check:deps pnpm script` (T4)

## Test Outcomes

| Task | RED | GREEN |
|------|-----|-------|
| T2   | 3 (all failed: script missing) | n/a |
| T3   | n/a | 3/3 passed |
| T4   | n/a | regression 57/479, check:deps end-to-end OK |

## Discoveries / Risks

- **Shellcheck not installed on host** — `shellcheck` command not found in PATH; CI `Shellcheck` job will catch issues locally.
- **Corepack not preinstalled** — installed via `npm install -g corepack`; pnpm 10.12.1 honored inside `frontend/`.
- **`corepack pnpm --dir frontend ...` from repo root fails on this host** (pre-existing corepack 0.34.7 + global pnpm 11.4.0 + Node 25 behavior; not introduced by this change). The canonical command `cd frontend && corepack pnpm ...` works. The frontend README documents both patterns.
- **Bug fixed during GREEN**: bash `for IMP in $IMPORTS_RAW` word-splits the grep output. Replaced with `while IFS= read -r LINE` to iterate grep output line-by-line.
- **Bug fixed during GREEN**: `${IMP#[\"\'\`}]` bash parameter expansion with character class did not strip quotes correctly. Replaced with `sed -E "s/^['\"\`]+//; s/['\"\`]+$//"` for portable quote-stripping.
- The install-failure test relies on `set -e` not aborting when `grep` finds no matches; both implementation and tests use `|| true` after grep.
- Sentinel is colocated with the lockfile (`frontend/.frontend-deps-ok`) per design decision.
- package.json scripts reordered alphabetically as part of T4: `build` and `check:deps` now sit before `dev`; `test:coverage` before `test:run`. The change is mechanical and does not affect any setting outside the `scripts` block.