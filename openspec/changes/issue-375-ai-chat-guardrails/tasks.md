# Tasks: issue-375-ai-chat-guardrails

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 420-560 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

## Acceptance checklist (Spec + Design mapping)

- [x] Spec: Permission failures remain HTTP 403 in `/api/ai/chat`.
- [x] Spec: Guardrail denials return HTTP 200 with stable `harness_result.denied=true`, `status="denied"`, and reason data.
- [x] Spec: Guardrail decision is evaluated before `maybe_run_harness(...)` for harness-backed intents.
- [x] Spec: No harness execution occurs when guardrail denies/escalates/fails closed.
- [x] Spec: Guard-denied and escalation paths return persisted denial payload and do not fabricate diagnostics.
- [x] Spec: Allowed harness path behavior remains unchanged, except for denial-only metadata when relevant.
- [x] Design: Availability guard uses canonical target IDs `ci:<ci.id>` via read-only resolution.
- [x] Design: `availability_check_batch` is fully guarded before any ping execution.
- [x] Design: `event_list`/`active_events` guard target is event query (`event_query:<status>:<severity-or-any>`) and does not emit cooldown-producing success.
- [x] Design: `record_operation(...)` is used; no `set_cooldown(...)` direct writes from chat path.
- [x] Design: No Raven runtime integration and no provider-native tool-calling added.
- [x] Canonical CI targets reject `id` values that are `None`, empty, or whitespace-only before guard and execution.

## Work-unit boundaries and rollback notes

- **PR 1 boundary**: Permission + guard decision + single-target deny/allow behavior.
  - Start: Current harness flow in `backend/routers/ai.py` and `backend/services/ai_chat_service.py`.
  - Finish: Guarded single intent path, structured denial payload, deterministic no-side-effect refusal.
  - Verify: New RED tests (Unit 1) pass and no chat test harness side effects on deny/escalation.
  - Rollback: revert `backend/routers/ai.py` and affected helper/test blocks.

- **PR 2 boundary**: Batch + event-list constraints + operation logging semantics.
  - Start: PR1 merged and test green.
  - Finish: Batch guard logic + canonical IDs + batch deny/recording behavior complete.
  - Verify: Batch and event-list GREEN tests pass and existing harness success semantics stay intact.
  - Rollback: revert PR2-only changes in `backend/routers/ai.py` and `backend/services/ai_chat_service.py`.

## Work Unit 1 — RED (tests first)

### 1.1 Permission and routing baseline
- **Target file:** `backend/tests/test_ai_chat_service.py`
- Add a new test to assert when intent capability is denied, response status is `403`, and guard/service mocks (`check_all_guards`, `maybe_run_harness`) are not called.

### 1.2 No-guard for non-harness chat
- **Target file:** `backend/tests/test_ai_chat_service.py`
- Add test for non-harness chat (`intent is None`) that asserts `check_all_guards(...)` and deterministic harness guard helpers are not called, while normal LM response path is used.

### 1.3 Canonical CI target before guard
- **Target file:** `backend/tests/test_ai_chat_service.py`
- Add a failing test that sends availability intent with alias/display `ci_ref` and asserts:
  - guard check receives `ci:<resolved_ci.id>` (no `ci_ref:` prefix),
  - no ping/external availability executor is called before guard decision.

### 1.4 Guarded deny path (single availability)
- **Target file:** `backend/tests/test_ai_chat_service.py`
- Add test with `check_all_guards(allowed=False, reason_code, cooldown)` + permission present:
  - HTTP `200`,
  - `harness_result.denied is True`, `status == "denied"`, has `reason`/`reason_code`,
  - persisted chat row stores same `harness_result`,
  - `maybe_run_harness(...)` not called.

### 1.5 Escalation-required first-slice behavior
- **Target file:** `backend/tests/test_ai_chat_service.py`
- Add test with `escalation_required=True` and mock decision details:
  - HTTP `200`,
  - `harness_result.status == "denied"`, `denied=True`, `reason_code == "escalation_required"`, `escalation_required=True`,
  - no harness execution.

### 1.6 Fail-closed guard unavailable
- **Target file:** `backend/tests/test_ai_chat_service.py`
- Add test where guard evaluation raises:
  - response is `200`,
  - `harness_result.reason_code == "guard_unavailable"`,
  - answer text says safety could not be verified,
  - does not claim policy/cooldown blocked the request,
  - no harness execution.

### 1.7 Event-list deny and no cooldown success
- **Target file:** `backend/tests/test_ai_chat_service.py`
- Add test for `event_list` denied by guard:
  - guard target = `event_query:<status>:<severity-or-any>`,
  - `status == "denied"`, no harness side effects,
  - no `record_operation(..., result="success")` for event list success in this slice.

### 1.8 Event-list repeatability
- **Target file:** `backend/tests/test_ai_chat_service.py`
- Add test with two back-to-back allowed `event_list` calls:
  - both requests execute,
  - second request is not blocked by prior diagnose success cooldown because no success record is written for allowed event-list.

### 1.9 Allowed availability success contract
- **Target file:** `backend/tests/test_ai_chat_service.py`
- Add test asserting guard allow for availability keeps existing successful payload:
  - returned `harness_result` matches existing success shape,
  - no denial fields injected,
  - `record_operation(..., result="success", target_id="ci:<canonical-id>")` called.

### 1.10 Batch fully guarded before execution
- **Target file:** `backend/tests/test_ai_chat_service.py`
- Add test for `availability_check_batch` with two resolvable refs where one guard check denies:
  - HTTP `200` denied payload,
  - `maybe_run_harness(...)` never called,
  - resolved target ids are canonicalized and both considered in guard path,
  - no partial ping.

### 1.11 Batch unresolved ref handling
- **Target file:** `backend/tests/test_ai_chat_service.py`
- Add test with mixed resolved/unresolved CI refs:
  - unresolved refs return deterministic `ci_not_found` entries,
  - unresolved refs are not passed as guard targets,
  - if any resolved target is denied, no ping occurs for any resolved target.

## Work Unit 2 — GREEN (implementation)

### 2.1 Add pre-harness guard gate in route
- **Target file:** `backend/routers/ai.py`
- Replace the current direct call flow for harnessed intents with:
  - permission gate first,
  - build guard context,
  - guard evaluation before `maybe_run_harness(...)`,
  - denial branch that returns deterministic harness result and persists via existing exchange-saving path.

### 2.2 Canonicalize availability CI before guard
- **Target files:** `backend/routers/ai.py`, `backend/services/ai_chat_service.py`
- Ensure availability and batch availability resolve CI via read-only lookup first, then pass `ci:<ci.id>` to guard and recording.

### 2.3 Implement guarded decision handler (deny/escalate/fail-closed)
- **Target files:** `backend/routers/ai.py`, `backend/services/ai_chat_service.py`
- Add deterministic builder for denial payload including required fields: `denied`, `status`, `reason`, `reason_code`, and optional `cooldown_remaining_seconds`, `escalation_required`, `escalation_id`, `source="ai_guard_service"`.

### 2.4 Implement event-list/all event-like intents guard mapping
- **Target file:** `backend/routers/ai.py`
- Add target normalization for status/severity (`any` default), `event_query:*` target_id mapping, and one-to-one denied path with no pre-harness event lookups.

### 2.5 Implement full-batch guard precondition
- **Target file:** `backend/routers/ai.py`
- Add guard sequence for `availability_check_batch` that resolves all refs read-only, evaluates all relevant canonical targets before any ping, and fails the whole batch on any denied/escalated target.

### 2.6 Integrate `record_operation(...)` calls for slice behavior
- **Target file:** `backend/routers/ai.py`
- Add/adjust operation logging calls:
  - `result="blocked"` on denied,
  - `result="escalated"` where provided,
  - `result="success"` for allowed availability and per-target availability-batch success,
  - no cooldown-producing `success` writes for event-list/active-events in this slice.

### 2.7 Keep non-harness behavior unchanged
- **Target file:** `backend/routers/ai.py`
- Add regression guard to preserve existing LM Studio completion flow and payload shape when `intent` is absent or not a harness intent.

## Work Unit 3 — TRIANGULATE / REFACTOR

### 3.1 Triangulation and ordering checks
- **Target file:** `backend/tests/test_ai_chat_service.py`
- Add/adjust tests to verify the order boundary: `check_all_guards(...)` occurs before any harness executor / ping function call for denied and fail-closed paths.

### 3.2 Refactor for reviewability
- **Target files:** `backend/routers/ai.py`, `backend/services/ai_chat_service.py`
- Extract guard context/type helpers and assertion-friendly small functions if Unit 2 grows beyond single-screen blocks.
- Keep interfaces narrow and test each helper independently with failing/allowed/denied states.

## Scope-control notes

- Keep PR scope confined to `backend/routers/ai.py`, `backend/services/ai_chat_service.py`, and `backend/tests/test_ai_chat_service.py`.
- No schema changes.
- No Raven runtime integration and no model/provider-native tool-calling path introduction.
- No changes to frontend/response UI contracts outside `AIChatResponse`/`harness_result` fields required by this slice.
- If scope starts creeping into other files, pause and split into an additional PR with explicit exception notes and updated forecast.