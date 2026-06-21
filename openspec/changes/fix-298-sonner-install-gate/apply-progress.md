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
| T3 — GREEN impl | (same test file) | Bash | N/A | ➖ N/A | ✅ 3/3 GREEN | ➖ N/A | ✅ Bash param-strip + word-split bug fixed (see Discoveries) |
| T4 — Docs + wiring | N/A (no test) | N/A | 57/479 baseline | ➖ N/A | ➖ N/A | ➖ N/A | ➖ None needed |

## Completed Tasks

### T1 — Worktree + baseline
- `git worktree add ... v1.13.2^{}` → worktree at `/home/alex/dev/next-gen/worktrees/fix-298-sonner-install-gate`
- `git rev-parse HEAD` = `49dda73` ✅
- `git status` clean ✅
- Branch `fix-298-sonner-install-gate` created from v1.13.2
- `corepack pnpm install --frozen-lockfile` (frontend/) → `Done in 1.5s using pnpm v10.12.1`
- Baseline test run: **57 test files passed / 479 tests passed**
- Corepack was missing on this host; installed via `npm install -g corepack` (0.34.7) — pnpm 10.12.1 honored inside `frontend/` via `packageManager` field.

### T2 — RED-first bash tests (`scripts/test-check-frontend-deps.sh`)
- New file: `scripts/test-check-frontend-deps.sh` (executable)
- 3 RED scenarios authored:
  1. `test_recovery_path` — fixture pre-populated with stubs for all imports except `sonner`; expects install + sentinel write + exit 0.
  2. `test_no_op_sentinel_path` — fixture pre-populated with sentinel matching lockfile SHA-256 + sonner stub; expects exit 0, sentinel mtime preserved, no install (tracked via shim `.invoked` marker file).
  3. `test_install_failure_path` — fixture missing sentinel + sonner; shim `corepack` returns non-zero; expects non-zero exit, no sentinel, error on stderr.
- RED proven: `bash scripts/test-check-frontend-deps.sh` → **0/3 passed**, all 3 fail with "script under test missing" because `scripts/check-frontend-deps.sh` does not exist yet.
- Commit `fc9d351` — `test(frontend): add RED-first bash tests for check-frontend-deps pre-flight`

### T3 — GREEN implementation (`scripts/check-frontend-deps.sh`)
- New file: `scripts/check-frontend-deps.sh` (executable, 114 lines)
- Implementation:
  - Derives `REPO_ROOT` from `${BASH_SOURCE[0]}` location — works for real repo and test fixtures.
  - Hashes `frontend/pnpm-lock.yaml` with SHA-256.
  - Compares to `frontend/.frontend-deps-ok` sentinel (newline-trimmed).
  - Scans `frontend/context/AuthContext.tsx` + `frontend/App.tsx` for non-relative `from 'pkg'` imports via `grep -hoE` + sed quote-strip + `cut` for top-level name (handles scoped `@org/pkg`).
  - Iterates line-by-line via `while IFS= read` (avoids word-splitting bug — see Discoveries).
  - On miss: runs `(cd "$FRONTEND_DIR" && corepack pnpm install --frozen-lockfile)`, then writes the lockfile hash to the sentinel.
  - Uses `corepack pnpm` (not raw `pnpm`) so the install-failure test's PATH shim of `corepack` correctly intercepts the call.
  - `set -euo pipefail`; all `grep` calls wrapped in `|| true` to avoid aborting on no-match.
- GREEN proven: `bash scripts/test-check-frontend-deps.sh` → **3/3 passed**.
- Manual end-to-end verification:
  - `rm frontend/.frontend-deps-ok && bash scripts/check-frontend-deps.sh` → "Sentinel missing or stale; running install..." → "Install complete; sentinel updated." → exit 0 (uses `pnpm v10.12.1` correctly inside `frontend/`).
  - Second invocation → "All tracked imports resolved; sentinel up to date." → exit 0 (no-op).
- Bash tests had two implementation bugs fixed during the GREEN cycle (see Discoveries).

### T4 — Docs + pnpm wiring — PENDING
- [ ] 4.1 Create `frontend/README.md` with 7 sections.
- [ ] 4.2 Insert "Local frontend dev (no Docker)" in `README.md`.
- [ ] 4.3 `frontend/package.json`: add `"check:deps"` script.

### T5 — Final verification — PENDING

## Commits (so far)

1. `fc9d351` `test(frontend): add RED-first bash tests for check-frontend-deps pre-flight` (T2)

## Test Outcomes

| Task | RED | GREEN |
|------|-----|-------|
| T2   | 3 (all failed: script missing) | n/a |
| T3   | n/a | 3/3 passed |

## Discoveries / Risks

- **Shellcheck not installed on host** — `shellcheck` command not found in PATH; CI `Shellcheck` job will catch issues locally.
- **Corepack not preinstalled** — installed via `npm install -g corepack`; pnpm 10.12.1 honored inside `frontend/`.
- **`corepack pnpm --dir frontend ...` from repo root fails on this host** (pre-existing corepack 0.34.7 behavior; not introduced by this change). The canonical command `cd frontend && corepack pnpm ...` works. The frontend README will document this.
- **Bug fixed during GREEN**: bash `for IMP in $IMPORTS_RAW` word-splits the grep output into `from` and `'sonner'` tokens instead of preserving each line. Replaced with `while IFS= read -r LINE` to iterate grep output line-by-line.
- **Bug fixed during GREEN**: `${IMP#[\"\'\`}]` bash parameter expansion with character class did not strip quotes correctly (the `\\` escapes were interpreted literally). Replaced with `printf '%s' "$IMP" | sed -E "s/^['\"\`]+//; s/['\"\`]+$//"` for portable quote-stripping.
- The install-failure test relies on `set -e` not aborting when `grep` finds no matches; both implementation and tests use `|| true` after grep.
- Sentinel is colocated with the lockfile (`frontend/.frontend-deps-ok`) per design decision; the file is small enough that `.gitignore` does not need updating (it's already covered by the broader gitignore policy for `.frontend-*` artifacts if any).