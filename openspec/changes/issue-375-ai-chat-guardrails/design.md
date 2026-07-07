# Design: Harden `/api/ai/chat` harness execution with existing guardrails

This slice adds a permission-first guardrail gate to the backend-owned `/api/ai/chat` harness path. Allowed harnesses keep the current execution and response behavior; guardrail-denied or escalation-required harnesses do not execute and instead return/persist an explicit conversational denial in `harness_result` with HTTP 200.

## Quick path

1. Resolve or infer `intent` exactly as today.
2. Keep the existing `_can_run_intent_harness(...)` permission gate; permission failures remain HTTP 403.
3. Build guard metadata before harness execution. For availability intents, this may include **read-only CI resolution to canonical CI IDs**; it must not include ping, diagnostics, event lookup execution, or operation recording.
4. Before `maybe_run_harness(...)`, evaluate chat-harness guardrails through `ai_guard_service`.
5. If denied, escalation-required, or guard evaluation cannot safely complete, skip `maybe_run_harness(...)`, build a denial `harness_result`, render a deterministic denial answer, and persist it through `save_chat_exchange(...)`.
6. If allowed, execute the harness as today and record successful guard-tracked operation(s) only where doing so does not introduce unstable cooldown UX.

## CodeGraph note

The workspace does not contain a `.codegraph/` index and no CodeGraph tool is available in this executor environment, so design inspection used the explicit evidence files from the proposal/spec plus targeted reads of the affected files instead of broad repository exploration.

## Current integration seam

`backend/routers/ai.py::chat_with_ai` is the exact integration point.

Current flow:

```python
intent = body.intent or infer_chat_intent(body.query)
# maybe infer_followup_intent(...)
if intent is not None and not _can_run_intent_harness(intent, current_user):
    raise HTTPException(status_code=403, detail=detail)

harness_result = await asyncio.to_thread(maybe_run_harness, intent, neo4j_driver, current_user)
```

New flow:

```python
intent = body.intent or infer_chat_intent(body.query)
# maybe infer_followup_intent(...)
if intent is not None and not _can_run_intent_harness(intent, current_user):
    raise HTTPException(status_code=403, detail=detail)

guard_context = await asyncio.to_thread(build_chat_harness_guard_context, intent, neo4j_driver)
if guard_context.non_diagnostic_result is not None:
    harness_result = guard_context.non_diagnostic_result
else:
    guard_decision = await asyncio.to_thread(evaluate_chat_harness_guard, guard_context, current_user)
    if guard_decision.denied or guard_decision.escalation_required:
        harness_result = build_denied_harness_result(intent, guard_context, guard_decision)
    else:
        harness_result = await asyncio.to_thread(maybe_run_harness, intent, neo4j_driver, current_user)
        await asyncio.to_thread(record_chat_harness_success, guard_context, current_user, harness_result)
```

`complete_chat(...)` should deterministically render denied harness results before normal deterministic harness rendering. This avoids an LM Studio call to explain a denial and prevents fabricated diagnostics.

## Guard target canonicalization

Availability guard target identity must be canonical. Do **not** guard availability diagnostics using unresolved strings such as `ci_ref:<normalized ci_ref>` when the harness accepts user-facing references.

### Availability canonical target strategy

Before guard evaluation, perform a read-only CMDB lookup with the same safe resolution semantics used by the current harness seam (`resolve_ci_for_harness(...)`) or its extracted equivalent:

- The lookup is allowed before the guard because it is read-only target resolution.
- The lookup must not run ping, network diagnostics, event queries, operation logging, cooldown mutation, or any other harness side effect.
- If the CI resolves, guard and record against the canonical target ID: `ci:<ci.id>`.
- Preserve the original user-entered value only in `request_context` and user-facing result fields.
- If the CI does not resolve, do not execute the availability harness. Return the existing non-diagnostic `ci_not_found`-style result deterministically and do not record a successful diagnostic operation. This keeps the no-diagnostic-before-guard invariant without inventing an unstable guard target.

For `availability_check_batch`, resolve every requested CI reference read-only before guard evaluation:

- If one or more refs resolve, build one canonical target ID per resolved CI: `ci:<ci.id>`.
- If any requested ref is unresolved, return a batch result containing `ci_not_found` entries for those refs and no ping work for them.
- If the batch contains any resolved target, all resolved targets must pass guard evaluation before any ping executes.
- If any resolved target is denied or escalation-required, deny the whole batch and execute no partial ping work.

This keeps batch in the first slice and avoids both unresolved guard identities and partial guarded execution.

## Guard operation mapping

Use existing `ai_guard_service` operation semantics; do not add a new Raven/tool runtime and do not call `set_cooldown(...)` directly.

| Chat intent | Guard operation | Target type | Target IDs before harness execution | Recording after success | Notes |
|---|---:|---|---|---|---|
| `availability_check` | `diagnose` | `ci` | `ci:<canonical ci.id>` after read-only CI resolution | `result="success"` for resolved CI | No ping/diagnostic side effect occurs before guard. |
| `availability_check_batch` | `diagnose` | `ci` | one `ci:<canonical ci.id>` per resolved CI, max existing batch size | `result="success"` per resolved CI | Batch is fully guarded in this first slice. |
| `event_list` | `diagnose` for guard check only | `event_query` | `event_query:<status>:<severity-or-any>` | Do **not** record cooldown-producing success in this slice | Guard bulk/behavioral safety where practical, but avoid event-list cooldown UX instability. |
| `active_events` | `diagnose` for guard check only | `event_query` | `event_query:ACTIVE:<severity-or-any>` | Do **not** record cooldown-producing success in this slice | Treat as event-list alias. |

Rationale: `diagnose` is the existing read/diagnostic operation in `ai_guard_service.COOLDOWNS`. For availability diagnostics, the cooldown maps well to real ping execution. For event listing, mapping to `diagnose` is useful for safety checks, but recording `success` would set a diagnose cooldown on a broad query target and could make repeat event-list UX unstable. Therefore, event-list success recording is excluded from cooldown-producing operation recording in this first slice. Denied or guard-unavailable event-list attempts may still be logged as `result="blocked"` best-effort because blocked records do not set cooldown.

Target normalization:

- Trim whitespace.
- Lowercase event filters.
- Use canonical `ci.id` for availability target IDs after read-only resolution; do not lowercase or rewrite the canonical ID beyond the existing stored identifier.
- Replace empty severity with `any`.
- Preserve original user-facing values only in `request_context`, not in canonical target IDs.

## Guard decision handling

Treat a `GuardResult` as blocking when either:

- `allowed is False`, or
- `escalation_required is True`.

For this first slice, escalation is surfaced as a structured guardrail denial/escalation-required response with HTTP 200 and no harness execution. Do not attempt human-approval workflow creation in this change.

Escalation denial payload rules:

- `status`: `"denied"`
- `denied`: `true`
- `reason_code`: `"escalation_required"`
- `escalation_required`: `true`
- `escalation_id`: include when provided by `GuardResult`
- `reason`: use the guard reason, falling back to `"AI guardrail requires human approval before this harness can run."`

Best-effort operation logging may use `result="escalated"` when the operation log is written, but logging failure must not cause harness execution.

## Event-list vs availability-check vs batch behavior

### Event-list intents

- Guard once using the event query target ID before running `_run_event_list_harness(...)`.
- The guard check is for bulk/behavioral safety and guard-unavailable fail-closed behavior.
- If allowed, run `maybe_run_harness(...)` unchanged; scoped event filtering remains inside `_run_event_list_harness(...)`.
- Do not prefetch event IDs only for guardrails; that would move event-list harness behavior before the guard.
- Do not record `result="success"` for event-list in this slice, because current `record_operation(...)` sets cooldown on every success and the existing service has no no-cooldown success operation. This prevents repeat event-list requests from being blocked solely by a diagnose cooldown produced by the previous list query.

### Availability-check intent

- Resolve the requested CI reference to a canonical CI ID using a read-only lookup before guard evaluation.
- If unresolved, return a non-diagnostic `ci_not_found` result without invoking `maybe_run_harness(...)`, without pinging, and without recording diagnostic success.
- If resolved, guard `ci:<ci.id>` before any ping.
- If allowed, run the existing harness path unchanged for that CI and record success after the harness returns.
- If the harness result is `invalid_target`, success may still be recorded because the diagnostic harness was executed against the resolved CI and should enter cooldown/tracking.

### Availability-check-batch intent

- Keep batch guarded in the first slice.
- Resolve all requested CI refs read-only to canonical CI IDs before any guard decision or ping.
- Evaluate all resolved targets before executing any ping.
- Recommended helper behavior:
  - call `check_all_guards(current_user.username, "diagnose", canonical_target_ids)` once to preserve bulk detection,
  - additionally ensure per-target cooldown coverage by checking each canonical target with `check_all_guards(current_user.username, "diagnose", [target_id])` until a denial or escalation-required result is found.
- If any target is denied or escalation-required, deny the whole batch and execute no partial harness work.
- If all resolved targets are allowed, run the existing batch harness for resolved CIs and include non-diagnostic `ci_not_found` entries for unresolved refs.
- Record success for each resolved target ID after execution so `record_operation(..., result="success")` sets cooldown for every resolved CI.

## Denial result contract

Returned and persisted `harness_result` for guardrail denial must be stable and explicit:

```json
{
  "type": "availability_check",
  "status": "denied",
  "denied": true,
  "reason": "Cooldown active",
  "reason_code": "cooldown_active",
  "cooldown_remaining_seconds": 123,
  "operation": "diagnose",
  "target_type": "ci",
  "target_ids": ["ci:router-1-id"],
  "source": "ai_guard_service"
}
```

Field rules:

- `type`: original intent type when present; otherwise omit/`None` is not required because no harness exists.
- `status`: always `"denied"` for guardrail-denied and escalation-required outcomes.
- `denied`: always `true`.
- `reason`: human-readable guard reason; fallback to `"AI guardrail denied this harness execution."`.
- `reason_code`: normalized stable code where possible. Minimum codes: `cooldown_active`, `bulk_operation_too_large`, `behavioral_guard_denied`, `escalation_required`, `guard_unavailable`, `guard_denied`.
- `cooldown_remaining_seconds`: include only when the guard result provides it.
- `escalation_required` and `escalation_id`: include when escalation is required/provided.
- `operation`, `target_type`, `target_ids`: audit/debug fields from the mapping above.
- `source`: always `"ai_guard_service"` for this slice.

For `reason_code="guard_unavailable"`, wording must say the guardrail system could not verify safety. It must not say a policy or cooldown explicitly blocked the request.

Example deterministic answer:

> I cannot run that operational check right now because the AI guardrail system could not verify it was safe to proceed. No diagnostic or event lookup was executed.

For explicit denials, the answer may mention the guard reason:

> I cannot run that operational check right now because an AI guardrail blocked it: Cooldown active. No diagnostic or event lookup was executed.

This denial answer should be generated by a small renderer in `ai_chat_service` (or router-local helper if kept tiny), not by LM Studio.

## Recording and cooldown tracking

Use `record_operation(...)`; do not call `set_cooldown(...)` directly from the chat path.

| Outcome | `record_operation` call | Cooldown behavior |
|---|---|---|
| Guard denied | Best-effort `result="blocked"`, `blocked_reason=<reason>` | No cooldown is set by current service semantics. |
| Guard escalation required | Best-effort `result="escalated"`, `blocked_reason=<reason>` | No cooldown is set. |
| Guard unavailable before execution | Best-effort `result="blocked"`, `blocked_reason="guard_unavailable"`; no harness execution | No cooldown is set. |
| Availability harness allowed and executed | `result="success"` after harness returns | Existing `record_operation` sets cooldown for canonical CI target. |
| Batch availability allowed and executed | `result="success"` per resolved canonical CI after harness returns | Existing `record_operation` sets cooldown for each canonical CI target. |
| Event-list harness allowed and executed | No success record in this first slice | Avoids repeat event-list cooldown instability. |
| Harness execution raises | Preserve existing HTTP 503 behavior; optional best-effort `result="failed"` if target metadata is available | No cooldown is set unless service semantics change later. |

Suggested `record_operation(...)` parameters:

- `ai_persona`: `str(current_user.role)`.
- `ai_agent_id`: `current_user.username`.
- `operation`: mapped operation, currently `diagnose`.
- `target_type`: mapped target type (`ci` or `event_query`).
- `target_id`: each target ID for batch/success, or primary target ID for single/event-list.
- `target_name`: canonical CI name/original ref for availability, event query description for event-list.
- `request_context`: include `{"source": "ai_chat", "intent_type": intent.type}` plus safe intent fields (`status`, `severity`, `limit`, original `ci_ref`/`ci_refs` counts, not prompt text).

Implementation guardrail: wrap `record_operation(...)` calls so a denial response can still be returned if blocked-operation logging fails. For allowed successful execution, prefer not to fail the already-completed chat response solely because post-execution audit logging failed; log internally if a logger is available. The critical safety invariant is that guard evaluation must happen successfully before harness execution.

## Backward compatibility and failure handling

- Permission failures stay exactly as today: HTTP 403 from `_can_run_intent_harness(...)`.
- Non-harness chat (`intent is None`) bypasses guard evaluation and behaves as today.
- Allowed harness responses remain unchanged; do not add denial fields to successful harness results.
- Existing deterministic rendering for `event_list`, `availability_check`, and `availability_check_batch` remains unchanged when allowed.
- Guard-denied and escalation-required harnesses return HTTP 200 and persist the denial in `AIChatMessage.harness_result` through the existing `save_chat_exchange(...)` path.
- Guard evaluation exceptions fail closed: no harness execution, deterministic denial payload with `reason_code="guard_unavailable"`, wording that the guardrail system could not verify safety, and HTTP 200. This preserves the no-untracked-execution safety requirement.
- Existing `maybe_run_harness(...)` exceptions continue to return HTTP 503.
- No database schema changes are required.

## RED tests to write first

Strict TDD should add failing tests before implementation, likely in `backend/tests/test_ai_chat_service.py` because existing `/api/ai/chat` router tests already live there.

1. **Permission failure remains 403**
   - Given an availability intent and a user without diagnostic permission.
   - Assert response is HTTP 403.
   - Assert `check_all_guards` and `maybe_run_harness` are not called.

2. **Canonical CI identity is used before availability guard**
   - Given a permitted availability user and `ci_ref` supplied as a display name/alias accepted by the resolver.
   - Mock read-only CI resolution to return `{"id": "ci-123", "name": "Router A"}`.
   - Assert `check_all_guards` receives target ID `ci:ci-123`, not `ci_ref:<normalized input>`.
   - Assert no ping or harness executor runs before the guard decision.

3. **Guard denial returns HTTP 200 and does not execute harness**
   - Given a permitted availability user and `check_all_guards.allowed=False` with reason/cooldown.
   - Assert response HTTP 200.
   - Assert `harness_result.denied is True`, `status == "denied"`, reason fields exist.
   - Assert `maybe_run_harness` is not called.
   - Assert persisted fake DB row has the same `harness_result`.

4. **Escalation-required guard result denies execution in first slice**
   - Given `check_all_guards` returns `allowed=True` and `escalation_required=True`.
   - Assert response HTTP 200 with `harness_result.denied is True`, `reason_code == "escalation_required"`, and `escalation_required is True`.
   - Assert `maybe_run_harness` is not called.
   - Assert best-effort logging uses an escalated/blocked non-success result and sets no cooldown.

5. **Denied event-list uses event-query target without cooldown-producing success**
   - Given permitted event-view user and explicit `event_list` intent.
   - Assert `check_all_guards` called with operation `diagnose` and target like `event_query:active:any`.
   - Assert no event harness execution when denied.

6. **Repeat event-list behavior remains stable when allowed**
   - Given two consecutive permitted `event_list` requests with the same query target.
   - Mock guard allow for both.
   - Assert both can execute and the first success does not create a diagnose cooldown that blocks the second.
   - Assert no `record_operation(..., result="success")` call is made for event-list in this slice.

7. **Allowed availability path preserves current behavior**
   - Given permitted diagnostic user, canonical CI resolution, and `check_all_guards.allowed=True`.
   - Mock `maybe_run_harness` to return an availability result.
   - Assert response harness result equals the harness result and no denial fields are injected.
   - Assert `record_operation(..., result="success", target_id="ci:<canonical id>")` is called.

8. **Batch is fully guarded before execution**
   - Given `availability_check_batch` with two resolvable CI refs.
   - Mock canonical resolution to two CI IDs.
   - Mock second per-target guard check denied.
   - Assert HTTP 200 denial and `maybe_run_harness` not called.
   - Assert target IDs include both canonical CI IDs and no partial ping work occurs.

9. **Batch handles unresolved refs without unguarded diagnostics**
   - Given `availability_check_batch` with one resolvable and one unresolved CI ref.
   - Assert the resolved CI is guarded by canonical ID before any ping.
   - Assert unresolved ref produces `ci_not_found` content and is not represented by an unresolved guard target.
   - Assert no ping executes if any resolved target is denied.

10. **Guard failure fails closed with accurate wording**
    - Mock `check_all_guards` to raise.
    - Assert HTTP 200 with `harness_result.reason_code == "guard_unavailable"`.
    - Assert answer says the guardrail system could not verify safety.
    - Assert answer does not claim a policy/cooldown explicitly blocked the request.
    - Assert no harness execution and denial is persisted.

11. **Non-harness chat stays untouched**
    - Given ordinary chat with no inferred intent.
    - Assert guard service is not called and existing LM Studio completion path remains active.

## File-change plan

Expected application changes for the next phase:

| File | Purpose | Estimate |
|---|---|---:|
| `backend/routers/ai.py` | Add guard context build/evaluation before `maybe_run_harness`, canonical availability targets, recording hooks, denial branch | ~110-165 lines |
| `backend/services/ai_chat_service.py` | Extract/reuse read-only CI resolution, add deterministic denial renderer / denial-aware `complete_chat` branch if not router-local | ~35-65 lines |
| `backend/tests/test_ai_chat_service.py` | RED tests for canonical identity, denial, escalation, repeat event-list, batch, failure, compatibility | ~160-230 lines |

Estimated changed lines: **305-460**. The canonical target and batch requirements may push the final diff over the 400-line review budget. Do not defer batch hardening while it remains in scope; if the implementation cannot stay reviewable, split only after a task-level PR boundary that still keeps batch guarded within the planned chain.

PR slicing risk: **medium**. The slice remains localized, but canonical resolution plus batch and denial persistence tests increase review load. If chained PRs are needed, keep the first implementation PR internally coherent: guard context/denial renderer/availability single target first, then batch/event-list follow-up before closing the spec.

## Out of scope

- No Raven runtime adapter, Raven write path, Raven read bridge, or Raven-backed guard decisions.
- No provider-native tool calling, OpenAI function-calling loop, model-selected tools, or model-executed tools.
- No new harness families.
- No permission model redesign.
- No `ai_guard_service` schema migration or cooldown model redesign.
- No human-approval workflow implementation for escalations in this slice.
- No UI redesign.

## Review checklist

- [ ] Guard evaluation happens after permission approval and before `maybe_run_harness(...)`.
- [ ] Availability guard target IDs are canonical `ci:<ci.id>` values resolved read-only before guard evaluation.
- [ ] No ping, event lookup execution, operation recording, or diagnostic side effect occurs before guard approval.
- [ ] Permission failures still return HTTP 403.
- [ ] Guard denials and escalation-required results return HTTP 200 with persisted `harness_result.denied == true`.
- [ ] `guard_unavailable` wording says safety could not be verified, not that policy/cooldown blocked it.
- [ ] Denied paths do not execute ping, event lookup, or any harness executor.
- [ ] Batch availability is fully guarded; no partial ping work occurs after any denied/escalated target.
- [ ] Repeat event-list requests are not destabilized by diagnose cooldown from prior successful event-list calls.
- [ ] Allowed harness result shape remains unchanged.
- [ ] `record_operation(...)` is used for blocked/escalated/availability-success tracking; no direct cooldown writes from chat.
- [ ] Raven and provider-native tool calling remain absent.
