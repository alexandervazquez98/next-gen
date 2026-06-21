# Archive Report — fix-292-stale-recovery-rate-limit

## Status

**Archive status:** PASS  
**Archived on:** 2026-06-20  
**Main SHA at archive:** `977209a385b3a9759ba08b68abd7bccffc2d13e1` (post-merge with archive move; merge commit `977209a` = `Merge pull request #293 from alexandervazquez98/fix/292-stale-recovery-rate-limit`)  
**Artifact store mode:** `hybrid` (filesystem audit trail + Engram observation)  
**Issue:** `alexandervazquez98/next-gen#292` (CLOSED — auto-closed by PR #293 merge)  
**Linked PR:** `alexandervazquez98/next-gen#293` (Closes #292, MERGED, single-PR cycle)  
**Change ID:** `fix-292-stale-recovery-rate-limit`

## Merged PR (audit trail)

| PR | Title | Merge commit | Branch path | State |
|---|---|---|---|---|
| #293 | fix(auth): honor should_count_rate_limit in ROTATED_STALE_RECOVERABLE branch (#292) | `977209a385b3a9759ba08b68abd7bccffc2d13e1` | `fix/292-stale-recovery-rate-limit` → `main` | MERGED |

The PR merged as a non-linear merge commit on `main` (the worktree had four linear commits on the branch which GitHub preserved in the merge commit's history).

## Synced main specs

| Capability | Action | Details |
|---|---|---|
| `auth-rate-limit-flag-honoring` | **Created** | New consolidated spec at `openspec/specs/auth-rate-limit-flag-honoring/spec.md`. 4 requirements (router flag honoring, terminal abuse counters, service flag guarantee, recovery atomic unchanged), 9 scenarios lifted from the delta. Includes `## Out of Scope` section listing the 5 deferred items. |

**Modified capabilities**: None (per proposal).

## Test counts

- Targeted: `uv run pytest backend/tests/test_auth_router_refresh.py backend/tests/test_auth_service_refresh.py -v` → **65 passed, 0 failed**.
- Individual 9 scenario tests → **9 passed, 0 failed** (`1.13s`).
- Backend test tree: `uv run pytest backend/tests` → **1067 passed, 97 failed, 1 skipped** (`5.78s`).
- Pre-existing unrelated failures: 97 across 13 backend test files (`test_auth_extended.py`, `test_backup_service.py`, `test_cli_worker.py`, `test_dictionary_service.py`, `test_event_correlation.py`, `test_routers_dictionaries.py`, `test_routers_events.py`, `test_routers_links.py`, `test_routers_metrics_events.py`, `test_routers_nodes.py`, `test_rtu_integration.py`, `test_rtu_sensor_repo.py`, `test_rtus_router.py`). These were present on `main@e9557e0` BEFORE this change; the PR did NOT introduce them and does not fix them (correctly quarantined).
- 4/4 implementation tasks (T1 setup, T2 RED, T3 fix, T4 regression, T5 service) completed; the T1-T5 hierarchy in `tasks.md` is fully checked.

## Out-of-scope items deferred

The following are intentionally NOT covered by this archive:

- **Telemetry for stale-rotation races** — no new logging/metrics/audit events for stale recovery counter behavior.
- **Router-wide flag-as-source-of-truth refactor** — the deferred follow-up mentioned in Req 1's note. The current spec guards `increment_attempts` only in the `ROTATED_STALE_RECOVERABLE` branch (`backend/routers/auth.py:404`); terminal abuse sites at lines 298, 307, 314, 321, 370, 377, 386, 394 remain unguarded by design.
- **Recovery atomic change** — `try_increment_refresh_recovery_count` at `backend/services/auth_service.py:378-397` is unchanged.
- **`stale_rotation_max_recoveries` value change** — config untouched.
- **Any frontend work** — the bug is server-only; no frontend commits.

## Lessons learned

- **Spec gatekeeper review caught scope drift early.** The exploration → propose → spec → design → tasks flow surfaced a spec-overreach in Req 2, where scenarios required broader changes than the proposal's "surgical fix" framing allowed. The design-phase gatekeeper flagged this; the spec was revised BEFORE implementation. **Lesson: spec gatekeeper review is valuable for catching scope drift early.**
- **Test line-budget calibration for security-critical router tests.** Tasks forecast 180-250 lines; actual PR diff was 420 lines (router tests ballooned to +326 lines because each scenario needs its own fixture, atomic patch, increment-attempts patch, and DB row assertion). The 4-commit split (RED router → fix → regression → service) kept individual commits reviewable. **Lesson: budget lines per test should be ~50 lines, not ~30, for security-critical router tests.**
- **Document "wrong-reason" passes explicitly.** The existing `test_stale_refresh_recoverable_does_not_increment_rate_limit` passed today for the wrong reason: the recovery atomic returns `True` and short-circuits before the buggy line. The design called this out explicitly, and the verify phase confirmed it with `increment_attempts.assert_not_called()` while atomic returns `True`. **Lesson: when adding a regression test next to an existing passing test, document WHY the existing test passes; otherwise the new test copies the broken pattern.**
- **Quarantine pre-existing failures.** 97 pre-existing test failures in 13 unrelated backend test files on `main@e9557e0` were correctly isolated and not fixed in this PR. **Lesson: pre-existing failures should be quarantined in a separate work item, not bundled into a surgical fix PR.**
- **Always read line numbers from `git show main:path`, never the local working tree.** The parent worktree was on `cicd/cd-lane` (behind main), which confused the design agent's initial line-number read for `backend/services/auth_service.py` (orchestrator-cited lines were ~140 lines off: `verify_refresh_token` actually starts at `:261`, not `:134`). SHA matches exactly; only the local line numbers were stale. **Lesson: when reading line numbers for a fix, ALWAYS use `git show main:path`, never the local working tree, especially when the parent worktree is on a different branch.**

## Archived path

- Source: `openspec/changes/fix-292-stale-recovery-rate-limit/`
- Target: `openspec/changes/archive/2026-06-20-fix-292-stale-recovery-rate-limit/`
- Archive commit lands on `main` at the tip after the merge commit `977209a` plus the archive commit itself.
- Archive folder contents: `proposal.md`, `design.md`, `tasks.md`, `verify-report.md`, `apply-progress.md`, `specs/auth-rate-limit-flag-honoring/spec.md` (delta spec for historical record), `archive-report.md` (this file).

## SDD cycle close

- Status: **complete**
- All 4 implementation tasks (T1-T5) verified by the verify phase with 9/9 scenarios passing.
- Consolidated spec is the new source of truth at `openspec/specs/auth-rate-limit-flag-honoring/spec.md`.
- Local `fix/292-stale-recovery-rate-limit` worktree and branch removed; remote branch deleted by `gh pr merge --delete-branch`.
- Issue #292 CLOSED.

## Engram trace IDs

For traceability across the SDD cycle:

- Proposal: `#2334` (`sdd/fix-292-stale-recovery-rate-limit/proposal`)
- Spec (delta): `#2335` (`sdd/fix-292-stale-recovery-rate-limit/spec`)
- Design: `#2337` (`sdd/fix-292-stale-recovery-rate-limit/design`)
- Tasks: `#2341` (`sdd/fix-292-stale-recovery-rate-limit/tasks`)
- Apply progress: `#2342` (`sdd/fix-292-stale-recovery-rate-limit/apply-progress`)
- Verify report: `#2345` (`sdd/fix-292-stale-recovery-rate-limit/verify-report`)
- Apply gate review: `#2340` (Reviewed fix-292 apply gate)
- Apply session summaries: `#2336`, `#2338`, `#2339`, `#2346`
- Exploration: `#2332` (fix-292 exploration: stale-recovery rate-limit counter bug)
- Archive report: see topic `sdd/fix-292-stale-recovery-rate-limit/archive-report` (this observation, mirrored to filesystem)