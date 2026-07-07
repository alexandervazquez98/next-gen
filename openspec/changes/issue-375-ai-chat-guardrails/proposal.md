# Proposal: Issue #375 — Guardrails for `/api/ai/chat` harness execution

## Problem statement
The `/api/ai/chat` harness execution path currently uses existing permission checks but does not consistently apply the same control-plane safety contract used by operational AI endpoints (`ai_guard_service`). This creates a control-plane gap: harness actions can be executed without the same cooldown/behavioral guard semantics and denial recording that other AI operations already enforce.

## Decision and intent
Unify chat harness execution in this slice with explicit, permission-first guardrails while preserving the current client-facing behavior. Specifically:
- keep existing `/api/ai/chat` behavior and UX stable,
- reuse `ai_guard_service` guard patterns where they already exist,
- require explicit denial outcomes to be surfaced and persisted when a harness action is blocked.

## Scope (first slice)
**In scope (this change):**
1. Chat harness hardening around backend execution.
2. Permission checks remain as the first gate (no changes to permission model today).
3. Add `ai_guard_service`-based check-and-track for harness execution path.
4. Persist and return clear denial reasons when execution is blocked.
5. Ensure denial paths do not fabricate diagnostics and remain reviewable.

**Out of scope (first slice, documented boundaries):**
- Raven bridge runtime behavior.
- Model-native/tool-native calling loop implementation.
- New tool families or expansion of tool catalog.
- Major UI/workflow redesign.

## Affected areas
- Backend API entry for chat: `backend/routers/ai.py` (where `/api/ai/chat` is handled).
- Chat orchestration service: `backend/services/ai_chat_service.py` and harness execution flow.
- Guardrails service: `backend/services/ai_guard_service.py` integration points.
- Persistence/observability around `AIChatMessage.harness_result` and related denial records.
- Backend test coverage for denied/allowed chat harness flows.

## Proposed behavior
- On chat requests that resolve to a harness execution path, preserve existing permission checks.
- Before harness execution, run guardrail evaluation via existing `ai_guard_service` contract.
- If guardrails deny:
  - block harness run,
  - emit a concrete, non-fabricated reason in response and persisted chat record,
  - keep response shape stable and explicit about denial.
- If allowed: continue current deterministic/LLM flow and preserve existing successful behavior.
- Minimal compatibility-preserving changes only (no behavior shift to model-native execution).

## Risks and tradeoffs
| Risk | Impact | Tradeoff |
|---|---|---|
| Minimal hardening now | Leaves model-native tool calling unaddressed in this slice | Faster delivery and lower migration risk, but requires a later design for richer tool-call contract |
| Different guard lifecycle semantics | Potential mismatch in timeout/replay/rollback states | Keep guard contract explicit and auditable; defer broader framework convergence |
| Additional denial reasons in responses | Possible downstream assumptions on legacy harness outputs | Contract should define exact, stable denial payload fields |
| Persisting denials | Small runtime/storage overhead | Gains traceability and operational supportability |

## Rollback plan
Revert proposal-scope changes in chat harness path only; keep this localized so existing permission logic and chat responses can be restored immediately by disabling the new guardrail gate and denial persistence in chat harness handler.

## Success criteria
- **No harness execution occurs when guardrails deny.**
- **Existing permission checks remain intact** and continue to be the primary entitlement gate.
- **Denial reason is observable** in chat response and persisted record.
- **Tests cover denied and allowed harness paths** (including payload shape and persistence expectations).
- **No fabricated diagnostics** are returned.
- Target remains reviewable under **400 changed lines**, if possible.

## Next phase
Proceed to **spec**.

## Proposal question round (interactive)
To reduce ambiguity before specs, please confirm these assumptions:
1. **Denial surface area:** Should a denied harness always return a 200 response with structured denial content, or should HTTP status change in specific denial categories?
2. **Reason fidelity:** Are free-text reasons acceptable, or must denial reasons always map to a fixed enum/code set for analytics and client handling?
3. **Persistence scope:** Should denials always be persisted as `harness_result` on the chat message, or only for denied harness executions with explicit intent?
4. **Permission model boundary:** Should the scope of permissions considered unchanged for this slice, or can we formalize one narrow additive condition in parallel (e.g., diagnostic-role-only for availability checks)?

### Assumptions for now
- Keep permission model unchanged in this slice.
- Keep response contract backward-compatible unless denied by guardrail, with minimal required new fields for explicit denial reason.
- Keep user-facing behavior stable except for explicit, truthful denial explanation.

Reply if any assumption should change, or request a second question round if needed.