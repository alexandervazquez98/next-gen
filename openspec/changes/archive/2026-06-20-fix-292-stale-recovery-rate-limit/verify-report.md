# Verification Report: fix-292-stale-recovery-rate-limit

**Status:** PASS WITH WARNINGS  
**Mode:** Strict TDD (`strict_tdd: true`)  
**Change:** `fix-292-stale-recovery-rate-limit`  
**Branch / HEAD:** `fix/292-stale-recovery-rate-limit` @ `462e3212f8896a43fa08fb1535f2b23fbb3ef0aa`  
**PR:** https://github.com/alexandervazquez98/next-gen/pull/293

## Summary

The implementation satisfies the spec scenarios. All 9 scenario tests pass at current HEAD, the surgical production fix is exactly the inline `if verification.should_count_rate_limit:` guard in `backend/routers/auth.py`, terminal-abuse regression guards also pass with the fix reverted, and no out-of-scope files are modified.

Warnings are non-blocking: the literal root command `uv run pytest` stops on a pre-existing collection error in `backend/scripts/test_single_ci_reconcile.py`; running the backend test tree (`uv run pytest backend/tests`) confirms the apply-agent baseline shape: `1067 passed, 97 failed, 1 skipped` across the same unrelated 13 backend test files. Also, the actual PR diff is 420 changed lines (`419 insertions, 1 deletion`), above the 180-250 forecast because router tests ballooned to +326 lines. The 4-commit split keeps review slices clear.

## Completeness Table

| # | Spec scenario | Test | Current HEAD | Original main / fix reverted | Notes |
|---:|---|---|---|---|---|
| 1 | Exhausted recovery does not increment rate-limit | `test_recoverable_stale_exhaustion_does_not_increment_rate_limit` | PASS | Fails as expected when fix is reverted | Asserts 401, `increment_attempts.assert_not_called()`, recovery atomic called, no `RateLimitAttempt` row. |
| 2 | Within-cap recovery does not increment rate-limit | `test_recoverable_stale_within_cap_does_not_increment_rate_limit` | PASS | Passes on main for the documented wrong reason | Wrong-reason guard confirmed: patches `routers.auth.increment_attempts` and asserts `assert_not_called()` while atomic returns `True`. |
| 3 | `token_id=None` recovery does not increment rate-limit | `test_recoverable_stale_token_id_none_does_not_increment_rate_limit` | PASS | Fails as expected when fix is reverted | Asserts 401, recovery atomic not called, `increment_attempts.assert_not_called()`, no `RateLimitAttempt` row. |
| 4 | REVOKED terminal-abuse still increments | `test_terminal_abuse_statuses_still_increment_rate_limit_revoked` | PASS | PASS | Asserts one refresh-token `RateLimitAttempt` row. |
| 5 | EXPIRED terminal-abuse still increments | `test_terminal_abuse_statuses_still_increment_rate_limit_expired` | PASS | PASS | Asserts one refresh-token `RateLimitAttempt` row. |
| 6 | MISSING/no token still increments | `test_missing_refresh_token_increments_rate_limit` | PASS | PASS | Asserts one refresh-token `RateLimitAttempt` row. |
| 7 | Every recoverable stale service result sets `should_count_rate_limit=False` | `test_all_rotated_stale_recoverable_paths_set_should_count_rate_limit_false` | PASS | N/A | Asserts `ROTATED_STALE_RECOVERABLE` and `should_count_rate_limit is False`. |
| 8 | Past-grace rotated token is rejected, not recoverable | `test_rotated_token_beyond_grace_is_stale_rejected_not_recoverable` | PASS | N/A | Equivalent boundary test added because `test_rotated_token_beyond_grace_is_rejected` already existed. Asserts `ROTATED_STALE_REJECTED` and not recoverable. |
| 9 | Recovery atomic contract unchanged | `test_try_increment_refresh_recovery_count_contract_unchanged` | PASS | N/A | Asserts `True` on one-row update, `False` on zero-row update, and commit called once in both branches. |

## Test Execution Summary

### Targeted suite

Command:

```bash
uv run pytest backend/tests/test_auth_router_refresh.py backend/tests/test_auth_service_refresh.py -v
```

Result: `65 passed, 0 failed, 0 skipped` in `1.34s`.

Per file:

| File | Passed | Failed | Skipped |
|---|---:|---:|---:|
| `backend/tests/test_auth_router_refresh.py` | 30 | 0 | 0 |
| `backend/tests/test_auth_service_refresh.py` | 35 | 0 | 0 |

New tests observed:

- `test_recoverable_stale_exhaustion_does_not_increment_rate_limit`
- `test_recoverable_stale_within_cap_does_not_increment_rate_limit`
- `test_recoverable_stale_token_id_none_does_not_increment_rate_limit`
- `test_terminal_abuse_statuses_still_increment_rate_limit_revoked`
- `test_terminal_abuse_statuses_still_increment_rate_limit_expired`
- `test_missing_refresh_token_increments_rate_limit`
- `test_all_rotated_stale_recoverable_paths_set_should_count_rate_limit_false`
- `test_rotated_token_beyond_grace_is_stale_rejected_not_recoverable`
- `test_try_increment_refresh_recovery_count_contract_unchanged`

### Individual scenario run

Command: explicit 9-test pytest node selection.  
Result: `9 passed, 0 failed, 0 skipped` in `1.13s`.

### Full backend suite

Literal requested command from repo root:

```bash
uv run pytest
```

Result: collection stops before test execution on a pre-existing unrelated import error:

```text
ERROR backend/scripts/test_single_ci_reconcile.py
ModuleNotFoundError: No module named 'database'
collected 1165 items / 1 error
```

Backend test tree run used to validate the known baseline failures:

```bash
uv run pytest backend/tests
```

Result: `1067 passed, 97 failed, 1 skipped` in `5.78s`.

Pre-existing failure files (same 13 unrelated files listed by apply):

1. `backend/tests/test_auth_extended.py`
2. `backend/tests/test_backup_service.py`
3. `backend/tests/test_cli_worker.py`
4. `backend/tests/test_dictionary_service.py`
5. `backend/tests/test_event_correlation.py`
6. `backend/tests/test_routers_dictionaries.py`
7. `backend/tests/test_routers_events.py`
8. `backend/tests/test_routers_links.py`
9. `backend/tests/test_routers_metrics_events.py`
10. `backend/tests/test_routers_nodes.py`
11. `backend/tests/test_rtu_integration.py`
12. `backend/tests/test_rtu_sensor_repo.py`
13. `backend/tests/test_rtus_router.py`

None of these files is modified by the PR diff.

## Spec Scenario Validation Notes

- Scenarios 1-3 directly exercise the `ROTATED_STALE_RECOVERABLE` branch with `should_count_rate_limit=False` and verify the `Then` clauses through `increment_attempts.assert_not_called()` plus DB row absence. RED evidence was re-checked by reverting only `c1d4655`: scenario 1 and 3 fail because `increment_attempts` is called once; scenario 2 still passes for the documented atomic short-circuit reason.
- Scenarios 4-6 are regression guards. They pass at HEAD and also pass with the production fix reverted, proving terminal statuses were not changed by this PR.
- Scenario 8 uses the added equivalent `test_rotated_token_beyond_grace_is_stale_rejected_not_recoverable` instead of the already-existing exact-name test. This is consistent with apply-progress and adds the explicit `status != ROTATED_STALE_RECOVERABLE` boundary assertion.
- No deviation was found between the spec `Then` clauses and test assertions.

## Production Change Verification

`git show c1d4655 -- backend/routers/auth.py` confirms:

- Only `backend/routers/auth.py` was modified by the production commit.
- Diff is exactly `3` changed lines: `2 insertions(+), 1 deletion(-)`.
- The stale-recovery `increment_attempts` call is wrapped with the inline guard:

```diff
-            increment_attempts(rate_limit_key, identity_type="refresh_token")
+            if verification.should_count_rate_limit:
+                increment_attempts(rate_limit_key, identity_type="refresh_token")
```

Other refresh-token `increment_attempts` call sites are untouched and remain at current HEAD:

- `backend/routers/auth.py:298` — MISSING
- `backend/routers/auth.py:307` — EXPIRED
- `backend/routers/auth.py:314` — REVOKED
- `backend/routers/auth.py:321` — IDLE_EXPIRED
- `backend/routers/auth.py:370` — USER_INACTIVE
- `backend/routers/auth.py:377` — ROTATED_STALE_REJECTED
- `backend/routers/auth.py:385` — no-user
- `backend/routers/auth.py:393` — no-db-user
- `backend/routers/auth.py:405` — guarded ROTATED_STALE_RECOVERABLE exhausted path

No out-of-scope production changes were found.

## Wrong-Reason Guard Confirmation

`test_recoverable_stale_within_cap_does_not_increment_rate_limit` patches `routers.auth.increment_attempts` even when `try_increment_refresh_recovery_count` returns `True`, then asserts:

```python
increment_attempts.assert_not_called()
```

This is the required guard against the historical wrong-reason pass from atomic short-circuiting.

## Existing Test Isolation Confirmation

Command:

```bash
git diff main..HEAD -- backend/tests/test_auth_router_refresh.py | grep -A2 "test_stale_refresh_recoverable_does_not_increment_rate_limit" || true
```

Output:

```text
(no output)
```

The existing `test_stale_refresh_recoverable_does_not_increment_rate_limit` function body is unchanged from `main`.

## PR Diff Summary and Out-of-Scope Verification

`git diff main..HEAD --stat`:

```text
backend/routers/auth.py                    |   3 +-
backend/tests/test_auth_router_refresh.py  | 326 +++++++++++++++++++++++++++++
backend/tests/test_auth_service_refresh.py |  91 ++++++++
3 files changed, 419 insertions(+), 1 deletion(-)
```

`git diff main..HEAD --name-only`:

```text
backend/routers/auth.py
backend/tests/test_auth_router_refresh.py
backend/tests/test_auth_service_refresh.py
```

No frontend files, schema files, telemetry/logging changes, dependency files, or recovery atomic implementation files are modified.

## Forecast Accuracy Note

The actual diff is 420 changed lines (`419 insertions, 1 deletion`), exceeding the 180-250 line forecast. The overrun is test-size driven: `backend/tests/test_auth_router_refresh.py` added 326 lines for 6 router scenarios and explanatory strict-TDD comments. This is a warning, not a blocker, because the 4-commit split isolates review units: RED router tests, 3-line production fix, terminal-abuse regression tests, and service contract tests.

## Strict TDD Compliance

| Check | Result | Details |
|---|---|---|
| TDD evidence reported | PASS | `apply-progress.md` includes a TDD Cycle Evidence table for T2-T5. |
| RED confirmed | PASS | With `c1d4655` reverted, T2.1 and T2.3 fail on `increment_attempts.assert_not_called()`; T2.2 passes for the documented wrong reason. |
| GREEN confirmed | PASS | Targeted suite and all 9 scenario tests pass at HEAD. |
| Triangulation adequate | PASS | 9 tests cover 9 scenarios; stale recovery has exhausted, within-cap, and token_id=None branches. |
| Safety net | PASS | Existing targeted files pass; existing wrong-reason test remains unmodified. |
| Assertion quality | PASS | No tautologies, ghost loops, or assertion-without-production-call patterns found in the added tests. |

### Test Layer Distribution

| Layer | Tests | Files |
|---|---:|---:|
| Router integration | 6 | 1 |
| Service unit | 3 | 1 |
| E2E | 0 | 0 |
| **Total** | **9** | **2** |

Coverage analysis was not run; no coverage command was provided in the cached verification instructions.

## Risks / Blockers

### CRITICAL

None.

### WARNING

1. `uv run pytest` from repo root is blocked by a pre-existing unrelated collection error in `backend/scripts/test_single_ci_reconcile.py` (`ModuleNotFoundError: No module named 'database'`). Backend test-tree execution still confirms the known `1067 passed / 97 failed / 1 skipped` baseline.
2. Diff size exceeded forecast due to router test volume (+326 lines).
3. Proposal/spec/design/tasks were not present in the verification worktree's untracked OpenSpec directory; verification read those artifacts from the canonical project worktree while writing this report to the requested change path.

### SUGGESTION

- Before archive, consider syncing the OpenSpec proposal/spec/design/tasks into the PR worktree so future verification does not depend on a second worktree for artifacts.

## Verdict

PASS WITH WARNINGS. The spec behavior is covered by passing runtime tests, the production change is surgical and in scope, terminal abuse counting remains intact, and no out-of-scope files changed. Recommended next step: archive.
