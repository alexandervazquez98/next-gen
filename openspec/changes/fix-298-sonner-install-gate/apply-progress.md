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
| T3 — GREEN impl | (same test file) | Bash | N/A | ➖ N/A | ✅ 3/3 GREEN (pending — T3) | ➖ N/A | ✅ Pending review |
| T4 — Docs + wiring | N/A (no test) | N/A | 57/479 baseline | ➖ N/A | ➖ N/A | ➖ N/A | ➖ None needed |

## Completed Tasks

### T1 — Worktree + baseline
- `git worktree add ... v1.13.2^{}` → worktree at `/home/alex/dev/next-gen/worktrees/fix-298-sonner-install-gate`
- `git rev-parse HEAD` = `49dda73` ✅
- `git status` clean ✅
- Branch `fix-298-sonner-install-gate` created from v1.13.2
- `corepack pnpm install --frozen-lockfile` (frontend/) → `Done in 1.5s using pnpm v10.12.1`
- Baseline test run: **57 test files passed / 479 tests passed** (no `--reporter=basic`, full vitest output)
- Corepack was missing on this host; installed via `npm install -g corepack` (0.34.7) — pnpm 10.12.1 honored inside `frontend/` via `packageManager` field.

### T2 — RED-first bash tests (`scripts/test-check-frontend-deps.sh`)
- New file: `scripts/test-check-frontend-deps.sh` (executable, 9968 bytes)
- 3 RED scenarios authored:
  1. `test_recovery_path` — fixture pre-populated with stubs for all imports except `sonner`; expects install + sentinel write + exit 0.
  2. `test_no_op_sentinel_path` — fixture pre-populated with sentinel matching lockfile SHA-256 + sonner stub; expects exit 0, sentinel mtime preserved, no install (tracked via shim `.invoked` marker file).
  3. `test_install_failure_path` — fixture missing sentinel + sonner; shim `corepack` returns non-zero; expects non-zero exit, no sentinel, error on stderr.
- RED proven: `bash scripts/test-check-frontend-deps.sh` → **0/3 passed**, all 3 fail with "script under test missing" because `scripts/check-frontend-deps.sh` does not exist yet. (This is the desired RED state — the test cannot exercise behavior that hasn't been written.)

## Commits (planned)

1. `<T2 commit>` `test(frontend): add RED-first bash tests for check-frontend-deps pre-flight`
2. `<T3 commit>` `feat(scripts): implement check-frontend-deps.sh pre-flight`
3. `<T4 commit>` `docs(frontend): add frontend README and root README local-dev pointer; wire check:deps pnpm script`

## Test Outcomes

| Task | RED | GREEN |
|------|-----|-------|
| T2   | 3 (all failed: script missing) | n/a (pending T3) |

## Risks / Discoveries

- **Shellcheck not installed on host** — `shellcheck` command not found in PATH; the repo's existing shell scripts include `# shellcheck disable=SC…` comments but cannot be validated locally. The CI job `Shellcheck` will catch issues.
- **Corepack not preinstalled** — had to `npm install -g corepack` once; now `corepack pnpm` honors the `pnpm@10.12.1` pin inside `frontend/`.
- The test fixture copies `frontend/App.tsx` from the repo at v1.13.2; this is consistent with the design decision to scope the import scan to just `AuthContext.tsx` + `App.tsx`.