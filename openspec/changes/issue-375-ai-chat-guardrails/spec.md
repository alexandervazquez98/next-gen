# /api/ai/chat Harness Guardrail Specification

## Purpose
The chat API MUST enforce a clear, two-layer decision model for harness execution requests: keep entitlement checks as the first gate, then run chat-harness guardrails before execution, while preserving existing behavior for allowed/unauthorized flows.

## Requirements

### Requirement: Permission failures and guardrail denials use distinct HTTP semantics
The system MUST return **HTTP 403** when `/api/ai/chat` request fails permission/entitlement checks.

The system MUST return **HTTP 200** when a request passes permissions but is denied by `ai_guard_service` during harness guardrail evaluation.

#### Scenario: Permission failure remains forbidden
- GIVEN a chat request requires a restricted intent permission
- WHEN the caller lacks the required permission
- THEN the response MUST be HTTP 403
- AND the response body MUST NOT be treated as a guardrail denial payload.

#### Scenario: Guardrail denial is conversationally stable
- GIVEN a caller has required permissions for a harness intent
- AND `ai_guard_service` denies execution for that request
- WHEN the request is processed
- THEN the response MUST be HTTP 200
- AND the response MUST preserve chat response shape while explicitly reporting denial status.

### Requirement: Guardrail evaluation occurs before chat harness execution
The system MUST evaluate guardrails for harness-backed intent requests **before** `maybe_run_harness` execution begins.

#### Scenario: Guardrails are checked prior to harness execution
- GIVEN a request resolves to a harness-capable intent
- WHEN processing reaches execution phase
- THEN the guardrail service MUST be consulted prior to any external command, ping, event lookup, or other harness side effects.
- AND execution decisions MUST be based on that guard decision result.

### Requirement: No harness execution when guardrails deny
The system MUST NOT execute harness actions when guardrails deny an execution attempt.

#### Scenario: Denied harness is not executed
- GIVEN a guardrail decision of `deny`
- WHEN a harness intent is requested
- THEN no harness executor SHALL run
- AND no backend side effects from that harness intent SHALL occur.

### Requirement: Denied harness result is explicit, structured, persisted, and returned
The system MUST return and persist a structured `harness_result` containing at minimum:
- `denied: true`
- `status: "denied"`
- human-readable reason text
- where available, a reason code

The system MUST NOT fabricate diagnostic content when producing denial output.

#### Scenario: Denial payload is explicit and persisted
- GIVEN a harness request is blocked by guardrails
- WHEN the API response is built
- THEN `harness_result.denied` MUST be `true`
- AND `harness_result.status` MUST be `"denied"`
- AND a reason MUST be present (`reason` and/or `reason_code`)
- AND the persisted chat message record MUST include this `harness_result` object.

### Requirement: Allowed path remains backward-compatible in this slice
When guardrails allow execution, the system MUST preserve existing successful chat behavior, including harness invocation flow and response shape, except for the new denial metadata field definitions in denied cases only.

#### Scenario: Allowed path behavior is unchanged
- GIVEN a request with sufficient permission and guardrail allow
- WHEN the harness executes
- THEN current harness behavior, prompt assembly, and persisted chat record semantics MUST match existing behavior for this path.
- AND no new denial fields are required in `harness_result`.

### Requirement: No Raven runtime integration and no provider-native tool calling in this slice
The system MUST NOT introduce Raven runtime integration in the `/api/ai/chat` harness execution path in this slice.

The system MUST NOT introduce provider-native/tool-call execution loops for this slice.

#### Scenario: Safety slice boundary is respected
- GIVEN any chat harness request in this first slice
- WHEN request handling is implemented
- THEN only backend-owned harness execution and existing LLM completion path are used.
- AND no additional Raven/runtime adapters are used for chat execution decisions.

### Requirement: Test expectations for denied and allowed paths
The system MUST be covered by tests that assert both denied and allowed harness outcomes, including status and persistence behavior.

#### Scenario: Denied harness path test
- GIVEN harness-eligible input with permission present
- AND mocked guardrails return deny
- WHEN API is invoked
- THEN tests MUST assert HTTP 200, `harness_result.denied === true`, `harness_result.status === "denied"`, and that harness execution methods are not called.

#### Scenario: Allowed harness path test
- GIVEN harness-eligible input with permission present
- AND mocked guardrails return allow
- WHEN API is invoked
- THEN tests MUST assert harness execution occurs and persisted chat output still includes harness result content consistent with existing success behavior.

## Notes
- Proposal had no explicit Capabilities section; this change is treated as a first-slice new AI-chat guardrail slice with acceptance constraints scoped to this issue.
- This spec applies to `/api/ai/chat` backend harness execution only in this slice.
