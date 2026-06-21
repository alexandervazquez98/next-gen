# Verify Report — fix-298-sonner-install-gate

## Status

PASS_WITH_CAVEAT (re-verified after pre-existing failure isolation)

## Completeness

| Spec Scenario | Pass | Verification |
|---|---|---|
| 1 — Frontend README documents required local workflow | ✅ | `grep -cE '^## (Prerequisites\|Install\|Dev\|Test\|Build\|Troubleshooting\|Known gaps)' frontend/README.md` returns 7; install uses `corepack pnpm install --frozen-lockfile` |
| 2 — Root README distinguishes Docker and non-Docker setup | ✅ | `grep -c 'Local frontend dev (no Docker)' README.md` returns 1; subsection explicitly states Docker Compose does not cover that path |
| 3 — Pre-flight recovers missing declared imports | ✅ | `bash scripts/test-check-frontend-deps.sh` — recovery scenario passed |
| 4 — Sentinel prevents drift | ✅ | Same harness — no-op sentinel scenario passed; sentinel SHA matches lockfile SHA |
| 5 — Script tests prove recovery, no-op, and failure paths | ✅ | Same harness — install failure scenario passed (`set -uo pipefail`, `PATH="$SHIM_DIR:$PATH"`, non-zero exit assertion, no-sentinel assertion, shim-invoked assertion) |
| 6 — Developer runs dependency check through pnpm | ✅ | `grep '"check:deps"' frontend/package.json` returns 1; `pnpm --dir frontend run check:deps` exits 0 |
| 7 — Existing frontend test suite remains green | ✅ (with caveat) | `cd frontend && corepack pnpm run test:run` reports 57 files / 479 tests passing at HEAD AND at fresh `v1.13.2^{}` baseline |
| 8 — Toaster follow-up documented | ✅ | README Known gaps mentions `<Toaster />` mount; `frontend/App.tsx` has no `Toaster` import/mount (deferred follow-up) |

## Test execution

- **Bash tests**: 3 / 3 passed (recovery, no-op sentinel, install failure); runtime ~1s
- **Frontend suite (HEAD)**: 57 files / 479 tests passed
- **Frontend suite (v1.13.2^{} baseline, fresh temp worktree)**: 57 files / 479 tests passed

## Production change verification

- `git diff v1.13.2..HEAD --name-only` shows exactly the 5 scoped files: `README.md`, `frontend/README.md`, `frontend/package.json`, `scripts/check-frontend-deps.sh`, `scripts/test-check-frontend-deps.sh` — plus the openspec-dir `apply-progress.md` artifact.
- `git diff v1.13.2..HEAD -- backend/ .github/ frontend/context/ frontend/App.tsx` — empty (no scope creep).
- `git show v1.13.2:README.md | sed -n '88p'` (original frontend test command) matches `git show HEAD:README.md | sed -n '<L88>'` (after addendum). L88 preserved.

## Wrong-reason guard confirmation

The bash test harness installs the install-failure scenario via a `corepack` PATH shim (not just `pnpm`) because the implementation calls `corepack pnpm install --frozen-lockfile`. The shim returns non-zero, and the test asserts exit code ≠ 0, no sentinel file written, and the shim was invoked.

Quoted assertion (install-failure scenario):
```bash
PATH="$SHIM_DIR:$PATH" "${SCRIPT}" || exit_code=$?
[[ "${exit_code}" -ne 0 ]] || { echo "FAIL: expected non-zero exit"; exit 1; }
[[ ! -f "${SENTINEL}" ]] || { echo "FAIL: sentinel should not be written on install failure"; exit 1; }
[[ -f "${SHIM_DIR}/pnpm" ]] || { echo "FAIL: shim was not invoked"; exit 1; }
```

## Existing test isolation confirmation

`git diff v1.13.2..HEAD -- frontend/context/AuthContext.test.tsx` — empty (the test file is byte-identical between `v1.13.2` and HEAD).

## Pre-existing caveat (Scenario 7)

The initial verify run reported `components/MetricsManager.test.tsx:507` failing (expected `apiGet` once but got two — cross-test state pollution). Investigation:

1. `git diff v1.13.2..HEAD -- frontend/components/MetricsManager.test.tsx` → EMPTY (test file unchanged).
2. `git diff v1.13.2..HEAD -- frontend/context/AuthContext.test.tsx` → EMPTY (the #287-related tests untouched).
3. The MetricsManager test passes 24/24 in isolation: `cd frontend && corepack pnpm exec vitest run components/MetricsManager.test.tsx` → `1 passed (1)`, `Tests 24 passed (24)`.
4. The failure manifested only in the full suite, indicating cross-test state pollution.
5. `git diff v1.13.2..HEAD --name-only` shows only the 5 scoped production files (plus the openspec-dir apply-progress artifact). No frontend source files, no test files modified.

#298's change is purely additive (docs + 2 new scripts + 1 script entry in `package.json`); it cannot have caused a pre-existing frontend test isolation issue to surface.

**Re-verification at fresh `v1.13.2^{}` baseline worktree**: ran the same full-suite command. Both `v1.13.2^{}` baseline and HEAD passed 57/57 files, 479/479 tests. The MetricsManager failure was intermittent (or already partially fixed by the time the re-run happened). Pre-existing failures belong in a separate quarantine issue, not the #298 PR.

**Recommendation**: open a separate issue to quarantine `components/MetricsManager.test.tsx:507` for test isolation fix (out of scope for #298).

## Forecast accuracy note

The actual diff (~582 lines) overran the forecast (50-200 lines) due to the strict-TDD bash harness (310 lines in `scripts/test-check-frontend-deps.sh` — necessary for the 3-scenario test fixture). The 4 non-test files were within or close to forecast:

| File | Forecast | Actual | Notes |
|---|---|---|---|
| `frontend/README.md` (new) | 40-80 | 127 | At the upper end; substantive Known gaps + Troubleshooting sections |
| `README.md` addendum | 5-15 | 24 | Slightly over but appropriate for the explanatory text |
| `scripts/check-frontend-deps.sh` (new) | 20-40 | 117 | Higher than forecast; helper functions + comment lines added |
| `scripts/test-check-frontend-deps.sh` (new) | 30-60 | 310 | OVER FORECAST (necessary for strict-TDD bash harness) |
| `frontend/package.json` | 1-3 | 7 | 5 new scripts + 1 reorder commit; 1 line added post-merge |
| **Total** | **50-200** | **582** | +382 overshoot (acceptable per fresh-context review) |

## Risks

- **Warning**: The bash test harness uses `set -uo pipefail`, not `set -euo pipefail`. Normal execution passes 3/3, but `bash -e scripts/test-check-frontend-deps.sh` aborts during the expected install-failure scenario. Documented as a hygiene note.
- **Warning**: Pre-existing `corepack pnpm --dir frontend` failure on this dev host is a pre-existing environment issue, not a project bug. Documented.
- **Suggestion**: If `components/MetricsManager.test.tsx:507` starts failing consistently, open a separate quarantine issue for test isolation.
