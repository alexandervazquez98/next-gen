# Delta for ai-chat-harness-guardrails

## ADDED Requirements

### Requirement: REQ-AICHG-001 — `create_ci_proposal` intent requires AI_PROPOSE_CI permission

The system MUST treat any AI-driven attempt to propose a Configuration Item as a harness-backed intent named `create_ci_proposal`. The system MUST require the `AI_PROPOSE_CI` permission (an `AIPermission` enum member) on the caller before evaluating any guardrail. The system MUST return HTTP 403 when the caller lacks `AI_PROPOSE_CI`, regardless of any other permission or role attribute.

#### Scenario: AI agent without AI_PROPOSE_CI is denied at the guardrail layer

- GIVEN an `AI_*` role that does NOT carry `AI_PROPOSE_CI`
- WHEN the agent issues a `create_ci_proposal` intent with a manifest payload
- THEN the response MUST be HTTP 403
- AND the response body MUST NOT carry a `harness_result.denied=true` payload
- AND NO `:CIProposal` node MUST be created
- AND the existing two-layer contract MUST be preserved (permission denied is forbidden, never conversationally stable).

#### Scenario: AI agent with AI_PROPOSE_CI proceeds to guardrail evaluation

- GIVEN an `AI_*` role that carries `AI_PROPOSE_CI`
- WHEN the agent issues `create_ci_proposal` with a manifest payload
- THEN the permission check MUST pass
- AND the guardrail service MUST be consulted before any `:CIProposal` write.

### Requirement: REQ-AICHG-002 — Guard target uses `ci_proposal:<proposal_id>` for bulk and cooldown tracking

The system MUST key the `propose_ci` cooldown and bulk-detection guards on the canonical target `ci_proposal:<proposal_id>` once a proposal id exists, and on `ci_proposal:new` for submit-time bulk detection that counts submissions per agent. The system MUST NOT use raw manifest fields (e.g., `ci.id`) as the guard target, to prevent bypass by manifest mutation.

#### Scenario: Cooldown key is canonical regardless of manifest content

- GIVEN an agent that has submitted a proposal with `ci.id="X"`
- WHEN the agent submits another manifest with `ci.id="Y"`
- THEN both submissions MUST count toward the same per-agent bulk window
- AND the cooldown key MUST be the canonical `ci_proposal:<id>` (post-create) or `ci_proposal:new` (pre-create).

#### Scenario: Unresolved or empty proposal reference is non-executable

- GIVEN a guard target derivation that yields an empty or whitespace-only `proposal_id`
- WHEN the request is processed
- THEN no guard target SHALL be produced
- AND no `:CIProposal` write SHALL occur.

### Requirement: REQ-AICHG-003 — `propose_ci` cooldown mirrors existing CI write cooldown pattern

The system MUST extend the existing `ai_guard_service.COOLDOWNS` table with a `propose_ci` key whose TTL matches or is tighter than the existing `ci_metadata_update: 120s` cooldown. The system MUST emit a stable `reason_code` (e.g., `cooldown_active`) when a submit is denied for cooldown.

#### Scenario: Submit inside cooldown window is denied

- GIVEN an agent with `AI_PROPOSE_CI` that submitted a manifest 30 seconds ago
- WHEN the agent submits another manifest within the `propose_ci` cooldown window
- THEN the response MUST be HTTP 200 with `harness_result.denied=true`
- AND `harness_result.reason_code` MUST equal `cooldown_active`
- AND NO new `:CIProposal` MUST be created.

#### Scenario: Submit outside cooldown window is allowed

- GIVEN an agent whose last submit is older than the `propose_ci` cooldown TTL
- WHEN the agent submits a new manifest
- THEN the cooldown check MUST pass
- AND the request MUST proceed to bulk detection and (if allowed) `:CIProposal` creation.

### Requirement: REQ-AICHG-004 — Bulk detection escalates or denies at >5 proposals/hour from one agent

The system MUST escalate or deny (`escalation_required=true` or `denied=true`) when one agent has submitted more than 5 proposals in any rolling 60-minute window. The system MUST include the agent id, the rolling-window count, and the threshold in the `harness_result` context.

#### Scenario: Sixth proposal within an hour is escalated

- GIVEN an agent with 5 submits in the last 60 minutes
- WHEN the agent submits a 6th
- THEN the response MUST be HTTP 200
- AND `harness_result` MUST carry either `denied=true` or `escalation_required=true`
- AND `harness_result.reason_code` MUST be a stable code identifying bulk-threshold breach.

#### Scenario: Submissions outside the rolling window do not count

- GIVEN an agent with 5 submits that occurred more than 60 minutes ago
- WHEN the agent submits a new manifest
- THEN the bulk threshold MUST NOT be breached
- AND the request MUST proceed past bulk detection.

### Requirement: REQ-AICHG-005 — `create_ci_proposal` follows the same deny/escalate/fail-closed contract

The system MUST apply the existing two-layer contract to `create_ci_proposal`: deny, escalate, or fail-closed at the guardrail layer MUST result in no `:CIProposal` write, MUST return HTTP 200 with the structured `harness_result.denied` payload, and MUST persist the denial to `ai_operation_log` with `operation="propose_ci"`.

#### Scenario: Denied propose_ci is persisted and conversationally stable

- GIVEN an agent with `AI_PROPOSE_CI` whose request is denied by the guardrail
- WHEN the response is built
- THEN `harness_result.denied` MUST be `true`
- AND `harness_result.status` MUST be `"denied"`
- AND an `AIOperationLog` row with `operation="propose_ci"` and `result="blocked"` MUST be persisted
- AND NO `:CIProposal` MUST exist.

#### Scenario: Escalation-required propose_ci is not executed

- GIVEN an agent that crosses the bulk threshold
- WHEN the request is processed
- THEN no `:CIProposal` MUST be created
- AND the response MUST report `escalation_required=true` (or `denied=true`) with a stable `reason_code`.

## MODIFIED Requirements

None. The existing two-layer contract, deny/allow HTTP semantics, and Spanish-stem intent-inference requirements remain unchanged. The `create_ci_proposal` intent extends the harness surface additively without altering existing harness behaviors.

## REMOVED Requirements

None.

## RENAMED Requirements

None.

## ADDED Scenarios

Scenarios embedded in REQ-AICHG-001 through REQ-AICHG-005 above.

## MODIFIED Scenarios

None.