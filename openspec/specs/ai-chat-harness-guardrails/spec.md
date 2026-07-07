# AI Chat Harness Guardrails — Delta Specification

## Purpose

The chat API MUST enforce a clear, two-layer decision model for backend-owned harness execution: entitlement checks remain the first gate, then operational guardrails run before any harness side effect. Guardrail denials remain conversationally stable while preventing diagnostics, event lookups, and other harness work from executing.

## ADDED Requirements

### Requirement: Permission failures and guardrail denials use distinct HTTP semantics

The system MUST return **HTTP 403** when a `/api/ai/chat` request fails permission or entitlement checks.

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
- THEN the guardrail service MUST be consulted prior to any external command, ping, event lookup, or other harness side effects
- AND execution decisions MUST be based on that guard decision result.

### Requirement: No harness execution when guardrails deny, escalate, or fail closed

The system MUST NOT execute harness actions when guardrails deny an execution attempt, require escalation, or cannot verify safety.

#### Scenario: Denied harness is not executed

- GIVEN a guardrail decision of deny
- WHEN a harness intent is requested
- THEN no harness executor SHALL run
- AND no backend side effects from that harness intent SHALL occur.

#### Scenario: Escalation-required harness is not executed

- GIVEN a guardrail result with `escalation_required=true`
- WHEN a harness intent is requested
- THEN no harness executor SHALL run
- AND the response SHALL report a structured denied/escalation result.

#### Scenario: Guard unavailable fails closed

- GIVEN guard evaluation cannot safely complete
- WHEN a harness intent is requested
- THEN no harness executor SHALL run
- AND the response SHALL explain that safety could not be verified.

### Requirement: Denied harness result is explicit, structured, persisted, and returned

The system MUST return and persist a structured `harness_result` containing at minimum:

- `denied: true`
- `status: "denied"`
- human-readable reason text
- where available, a stable reason code

The system MUST NOT fabricate diagnostic content when producing denial output.

#### Scenario: Denial payload is explicit and persisted

- GIVEN a harness request is blocked by guardrails
- WHEN the API response is built
- THEN `harness_result.denied` MUST be `true`
- AND `harness_result.status` MUST be `"denied"`
- AND a reason MUST be present through `reason` and/or `reason_code`
- AND the persisted chat message record MUST include this `harness_result` object.

### Requirement: Availability guard targets use canonical CI identity

Availability-check guard targets MUST use canonical CI identity before any ping or diagnostic side effect. Missing, empty, or whitespace-only CI IDs MUST be treated as non-executable.

#### Scenario: Single availability uses canonical CI target

- GIVEN a user requests an availability check for a CI reference
- WHEN the backend resolves that reference read-only before guard evaluation
- THEN guard evaluation MUST use target ID `ci:<ci.id>`
- AND no ping or harness side effect SHALL occur before guard evaluation.

#### Scenario: Unresolved CI does not re-enter harness execution

- GIVEN the read-only CI resolution returns no CI
- WHEN the request is processed
- THEN the response SHALL return a deterministic `ci_not_found`-style result
- AND the system SHALL NOT call `maybe_run_harness`
- AND the system SHALL NOT perform a second resolution that could ping unguarded.

#### Scenario: Non-canonical CI ID is non-executable

- GIVEN read-only CI resolution returns a CI with missing, empty, or whitespace-only `id`
- WHEN the request is processed
- THEN no `ci:` blank target SHALL be produced
- AND no ping or harness execution SHALL occur.

### Requirement: Batch availability is fully guarded before any ping

Batch availability checks MUST resolve candidate CIs read-only, reject unguardable targets, evaluate guardrails for all executable canonical targets, and only then execute bounded pings.

#### Scenario: Batch denial blocks the whole batch

- GIVEN a batch availability request with multiple resolvable CIs
- AND any target is denied, escalated, or fails closed during guard evaluation
- WHEN the request is processed
- THEN no ping SHALL execute for any target
- AND no partial harness work SHALL occur.

#### Scenario: Batch unresolved refs are not guard targets

- GIVEN a batch availability request includes unresolved CI refs
- WHEN the request is processed
- THEN unresolved refs SHALL be represented as deterministic `ci_not_found` entries
- AND unresolved refs SHALL NOT be passed to guardrails as synthetic target IDs.

#### Scenario: Batch non-canonical CI IDs do not execute

- GIVEN a batch availability request resolves a CI with missing, empty, or whitespace-only `id`
- WHEN the request is processed
- THEN no blank `ci:` target SHALL be produced
- AND no ping or harness execution SHALL occur for that item.

### Requirement: Event-list guardrails do not create cooldown-producing success records

Event-list and active-event harnesses MUST use event-query guard targets for blocked-path safety, but allowed event-list success MUST NOT emit cooldown-producing diagnostic success records in this slice.

#### Scenario: Event-list uses event-query target

- GIVEN a user requests an event-list harness
- WHEN guardrails are evaluated
- THEN the guard target SHALL be `event_query:<status>:<severity-or-any>`.

#### Scenario: Repeat event-list remains stable

- GIVEN two allowed event-list requests use the same query target
- WHEN both requests are processed
- THEN the first allowed event-list request SHALL NOT create a diagnose success cooldown that blocks the second request.

### Requirement: Allowed path remains backward-compatible in this slice

When guardrails allow execution, the system MUST preserve existing successful chat behavior, including harness invocation flow and response shape, except for denial-only metadata in denied cases.

#### Scenario: Allowed path behavior is unchanged

- GIVEN a request with sufficient permission and guardrail allow
- WHEN the harness executes
- THEN current harness behavior, prompt assembly, and persisted chat record semantics MUST match existing behavior for this path
- AND no new denial fields are required in successful `harness_result` values.

### Requirement: No Raven runtime integration and no provider-native tool calling in this slice

The system MUST NOT introduce Raven runtime integration in the `/api/ai/chat` harness execution path in this slice.

The system MUST NOT introduce provider-native/tool-call execution loops for this slice.

#### Scenario: Safety slice boundary is respected

- GIVEN any chat harness request in this first slice
- WHEN request handling is implemented
- THEN only backend-owned harness execution and existing LLM completion path are used
- AND no additional Raven/runtime adapters are used for chat execution decisions.

### Requirement: Regression tests cover denied and allowed paths

The system MUST be covered by tests that assert denied and allowed harness outcomes, including status, persistence, target identity, no-side-effect ordering, and allowed-path compatibility.

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
