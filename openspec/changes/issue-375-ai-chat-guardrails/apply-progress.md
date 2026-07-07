# Apply Progress: issue-375-ai-chat-guardrails

- status: success
- started_slice: PR 1 (single-slice slice as requested by maintainer exception)
- next_recommended: verify
- started_at: 2026-07-07

## Completed implementation

- [x] Fixed single and batch availability CI resolution/guard flow in `backend/routers/ai.py` to evaluate guards before harness execution and to avoid repeated DB resolution.
- [x] Canonicalized guard targets to `ci:<ci.id>` and event-list targets to `event_query:<status>:<severity-or-any>`.
- [x] Added resolved-CI pre-handoff to service harness executor via `_resolved_ci` so `maybe_run_harness(...)` continues to own harness execution semantics while avoiding duplicate `resolve_ci_for_harness(...)` calls.
- [x] Preserved existing allowed-path behavior for operational responses (`availability`, `availability_check_batch`, and `event_list`) and guard-denial short-circuit handling.
- [x] Updated `backend/services/ai_chat_service.py` to accept explicit resolved CI hints and use them in `_run_availability_harness`/batch execution.
- [x] Ensured unresolved batch refs remain represented as `ci_not_found` and are not re-resolved at harness execution time.
- [x] Updated `backend/tests/test_ai_chat_service.py` assertions to reflect canonicalization/ordering behavior and confirmed all required edge cases pass.
- [x] Added regression coverage for two critical 4R cases: single availability `ci_ref` not found and batch availability with canonical-id-missing CI.
- [x] Verified both regression tests execute and enforce fail-closed behavior (no `maybe_run_harness`, no ping) when CI is unresolved or non-executable.
- [x] Fixed `_canonical_ci_target_id` to reject `None`, empty, and whitespace-only CI IDs, and aligned single availability behavior to return `ci_not_found` instead of attempting diagnostics.
- [x] Added regression coverage for single availability and batch availability with whitespace/empty canonical IDs to ensure no guard target `ci:` is emitted and no side effects occur.

## Files changed

- `backend/routers/ai.py`
- `backend/services/ai_chat_service.py`
- `backend/tests/test_ai_chat_service.py`
- `openspec/changes/issue-375-ai-chat-guardrails/tasks.md`
- `openspec/changes/issue-375-ai-chat-guardrails/apply-progress.md`

## Test commands run

- `/tmp/next-gen-issue375-py311/bin/python -m pytest backend/tests/test_ai_chat_service.py`
- `/tmp/next-gen-issue375-py311/bin/python -m py_compile backend/routers/ai.py backend/tests/test_ai_chat_service.py`

## TDD Cycle Evidence

| Task | RED | GREEN | TRIANGULATE | REFACTOR |
| --- | --- | --- | --- | --- |
| Work unit 1.10+ | ✅ (assertions for order/canonicalization and mixed batch handling were present/failing) | ✅ (`74 passed`) | ✅ `resolve_ci`/`run_ping`/blank-id call-order and guard target assertions exercised | ✅ small shim-path refactor (`_resolved_ci` injection) |
| Work unit 1.11 (canonical-id-missing hardening) | ✅ `test_availability_check_with_blank_canonical_ci_id_is_non_executable` and batch invalid-id regression added first | ✅ (`74 passed`) | ✅ whitespace and blank ID variants with no side effects and no `ci:` target usage | ✅ no structural refactor needed |

## Deviations / notes

- No scope creep beyond `backend/routers/ai.py`, `backend/services/ai_chat_service.py`, and `backend/tests/test_ai_chat_service.py`.
- Behavior remains deterministic for operational harness types in `complete_chat`, so some tests assert rendered availability text rather than raw patched LLM output.

## Remaining / follow-up tasks

- [ ] [Potential follow-up] Run `strict-TDD`-aligned broader suite and any additional cross-module regressions requested by reviewers.

## Workload / PR boundary

- Slice boundary completed: PR 1 / single-slice exception (guard ordering, canonicalization, batch resilience).
- Remaining risk: none in this targeted scope.
- Next boundary remains: **verify**.