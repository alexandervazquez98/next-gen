# Spec: cmdb-ai-proposals

## Purpose

Defines the AI-driven CMDB Configuration Item (CI) proposal lifecycle: an AI agent with `AI_PROPOSE_CI` submits a structured manifest that creates a DRAFT `:CIProposal` node in Neo4j; a human reviewer with `CI_APPROVE_PROPOSAL` approves (committing the live `:CI` via the existing write path) or revokes. Every state transition emits exactly one audit row carrying `proposal_id`, `version`, redacted manifest summary, and `previous_state → next_state`. The capability preserves the two-layer guard contract: missing permission → HTTP 403; guardrail denial → HTTP 200 with `harness_result.denied=true`.

## Requirements

### REQ-CMAP-001: Manifest schema validation

The system MUST validate every incoming manifest against a versioned schema (`schema_version: 1`) whose `ci` object requires `id`, `label`, `category` and accepts the documented `Node` fields (`brand`, `model`, `serialNumber`, `firmwareVersion`, `ip`, `owner`, `location_name`, `status`, `pollingInterval`, `metadata`, `snmp`). The system MUST reject manifests whose `ci.metadata` would override fields in `BLOCKED_AI_UPDATE_FIELDS`.

#### Scenario: Happy-path manifest passes validation

- GIVEN a manifest with `schema_version: 1` and a complete `ci` block
- WHEN the backend validates it
- THEN the manifest MUST be accepted and a `proposal_id` returned.

#### Scenario: Malformed manifest is rejected

- GIVEN a manifest missing required `id` or `label`, or with non-integer `schema_version`
- WHEN the backend validates it
- THEN the response MUST be HTTP 422
- AND the response MUST list the offending field path(s).

### REQ-CMAP-002: Category must resolve against live Catalog

The system MUST resolve `ci.category` against the live `:Category` set at both submit time and approve time. The system MUST reject the proposal (HTTP 422) when `ci.category` does not match a `:Category.name` returned by `GET /api/categories`.

#### Scenario: Unknown category is rejected at submit

- GIVEN a manifest with `ci.category = "FictionalDevice"`
- AND no `:Category` with that name exists
- WHEN the backend validates it
- THEN the response MUST be HTTP 422 with reason `unknown_category`.

#### Scenario: Category renamed between submit and approve is rejected at approve

- GIVEN a DRAFT proposal references category `Router`
- AND `Router` was renamed or deleted before approve
- WHEN the reviewer approves the proposal
- THEN the approve MUST fail with HTTP 409
- AND an audit row MUST still be written for the failed attempt.

### REQ-CMAP-003: Proposal creation writes a DRAFT with version=1

The system MUST create a `:CIProposal` node on submit with `status="DRAFT"`, `version=1`, `manifest_json` (verbatim), `proposed_by`, `proposed_role`, `created_at`, `updated_at`. The system MUST NOT touch the `:CI` label.

#### Scenario: Agent submits and receives a proposal id

- GIVEN an agent with `AI_PROPOSE_CI`
- WHEN the agent POSTs a valid manifest
- THEN the response MUST be HTTP 201
- AND the response MUST include a unique `proposal_id`
- AND a `:CIProposal` with `status="DRAFT"`, `version=1` MUST exist.

### REQ-CMAP-004: AI_PROPOSE_CI permission is the first gate

The system MUST require `AI_PROPOSE_CI` (an `AIPermission` enum member) on any submitter of `POST /api/cmdb/proposals`. The system MUST return HTTP 403 when the caller lacks it.

#### Scenario: AI role without AI_PROPOSE_CI is forbidden

- GIVEN a caller with an `AI_*` role but no `AI_PROPOSE_CI`
- WHEN the caller POSTs a manifest
- THEN the response MUST be HTTP 403
- AND the response MUST NOT include a `proposal_id`.

### REQ-CMAP-005: CI_APPROVE_PROPOSAL gates approve and revoke

The system MUST require `CI_APPROVE_PROPOSAL` (a `UserPermission` enum member) on every caller of `POST /api/cmdb/proposals/{id}/approve` and `/revoke`. The system MUST return HTTP 403 otherwise.

#### Scenario: Operator without CI_APPROVE_PROPOSAL is forbidden

- GIVEN a caller with `CI_EDIT` but no `CI_APPROVE_PROPOSAL`
- WHEN the caller attempts approve
- THEN the response MUST be HTTP 403.

#### Scenario: AI role is forbidden from approve

- GIVEN a caller with an `AI_*` role
- WHEN the caller attempts approve or revoke
- THEN the response MUST be HTTP 403 (no `AI_*` role carries `CI_APPROVE_PROPOSAL` in v1).

### REQ-CMAP-006: Approve transitions DRAFT → APPROVED and commits a CI

The system MUST transition `DRAFT → APPROVED` only from `status="DRAFT"`, MUST increment `version` to 2, MUST set `reviewed_by`, `reviewed_at`, `applied_manifest_json`, and `resulted_ci_id`, MUST call the existing `node_service.create_update_node()` to create the live `:CI`, and MUST write `(:CIProposal)-[:RESULTED_IN]->(:CI)`.

#### Scenario: Approve creates the live CI

- GIVEN a DRAFT proposal with valid category
- WHEN a reviewer with `CI_APPROVE_PROPOSAL` approves it
- THEN the response MUST be HTTP 200 with the new `:CI.id`
- AND `:CIProposal.status` MUST equal `APPROVED`
- AND `(:CIProposal)-[:RESULTED_IN]->(:CI)` MUST exist.

#### Scenario: Approve from non-DRAFT is rejected

- GIVEN a proposal whose status is `APPROVED` or `REVOKED`
- WHEN a reviewer attempts approve
- THEN the response MUST be HTTP 409
- AND the state MUST NOT change.

### REQ-CMAP-007: Revoke transitions to REVOKED without creating a CI

The system MUST transition `DRAFT → REVOKED` without creating a `:CI`. The system MUST also support `APPROVED → REVOKED`, which MUST mark the proposal REVOKED without deleting the already-committed `:CI`.

#### Scenario: Revoke from DRAFT leaves no CI

- GIVEN a DRAFT proposal
- WHEN a reviewer revokes it
- THEN `:CIProposal.status` MUST equal `REVOKED`
- AND NO `:CI` node with the proposed `id` MUST exist.

#### Scenario: Revoke from APPROVED leaves the CI in place

- GIVEN an APPROVED proposal with a linked `:CI`
- WHEN a reviewer revokes it
- THEN `:CIProposal.status` MUST equal `REVOKED`
- AND the `:CI` MUST remain in the graph.

### REQ-CMAP-008: Optimistic-version concurrency control

The system MUST require a matching `version` on every state-transition request. The system MUST execute transitions as `MATCH (p:CIProposal {id: $id, version: $v}) SET …` so the first writer wins and a concurrent attempt returns HTTP 409.

#### Scenario: Two reviewers approving concurrently — first wins

- GIVEN a DRAFT proposal at version=1
- WHEN reviewer A and reviewer B both POST approve with `version=1` near-simultaneously
- THEN exactly one response MUST be HTTP 200
- AND the other MUST be HTTP 409 with reason `version_conflict`.

### REQ-CMAP-009: CI id collision is rejected at submit

The system MUST reject (HTTP 409) any proposal whose `ci.id` already exists on a `:CI` node. The system MUST also surface this collision in the diff view's badge.

#### Scenario: Submit with colliding CI id is rejected

- GIVEN a `:CI` node with `id="CI-EXISTING"`
- WHEN an agent submits a manifest with `ci.id="CI-EXISTING"`
- THEN the response MUST be HTTP 409 with reason `ci_id_collision`.

### REQ-CMAP-010: AI guardrail cooldown and bulk detection for propose_ci

The system MUST extend `ai_guard_service` with a `propose_ci` cooldown key and MUST escalate or deny when one agent submits more than 5 proposals in any rolling 60-minute window.

#### Scenario: Bulk-proposal agent is escalated

- GIVEN an agent that has submitted 6 proposals in the last 60 minutes
- WHEN the agent submits a 7th
- THEN the response MUST be HTTP 200 with `harness_result.denied=true` (or `escalation_required=true`)
- AND a stable `reason_code` MUST be present.

### REQ-CMAP-011: Guardrail denial preserves the two-layer contract

When the caller has `AI_PROPOSE_CI` but the guardrail denies, the system MUST return HTTP 200 with a structured denial payload (`denied: true`, `status: "denied"`, `reason`, optional `reason_code`) and MUST NOT create a `:CIProposal`.

#### Scenario: Guardrail denial returns conversational 200

- GIVEN an agent with `AI_PROPOSE_CI` and an active `propose_ci` cooldown
- WHEN the agent submits
- THEN the response MUST be HTTP 200
- AND `harness_result.denied` MUST be `true`
- AND NO `:CIProposal` MUST be created.

### REQ-CMAP-012: Every state transition emits exactly one audit row

The system MUST record one audit row per transition with `event_type ∈ {CI_PROPOSAL_CREATE, CI_PROPOSAL_APPROVE, CI_PROPOSAL_REVOKE}` and context fields `proposal_id`, `proposed_by`, `actor_role`, `previous_state`, `next_state`, `version`, and an `applied_manifest_summary` whose secret fields are redacted.

#### Scenario: Create emits a CI_PROPOSAL_CREATE row

- GIVEN a successful submit
- WHEN the audit service persists
- THEN exactly one row with `event_type="CI_PROPOSAL_CREATE"`, `next_state="DRAFT"`, `version=1` MUST exist.

#### Scenario: Approve emits a CI_PROPOSAL_APPROVE row

- GIVEN a successful approve
- WHEN the audit service persists
- THEN exactly one row with `event_type="CI_PROPOSAL_APPROVE"`, `previous_state="DRAFT"`, `next_state="APPROVED"`, `version=2` MUST exist.

### REQ-CMAP-013: Audit redaction of secret-like fields

The system MUST redact the fields `snmp.community`, `snmp.authKey`, `snmp.privKey`, and any field name matching `*key|*token|*secret|*password` before persisting audit context. The system MUST never log raw payloads.

#### Scenario: SNMP community is redacted in audit

- GIVEN a manifest with `snmp.community = "public-ro-xyz"`
- WHEN an audit row is written
- THEN the persisted `applied_manifest_summary` MUST show `"community": "<REDACTED>"`.

### REQ-CMAP-014: List and detail endpoints are read-only and filterable

The system MUST expose `GET /api/cmdb/proposals` (filterable by `status`, `category`, `proposed_by`, date range) and `GET /api/cmdb/proposals/{id}` returning the full manifest and lifecycle metadata. Read endpoints MUST NOT mutate state.

#### Scenario: List filters by status

- GIVEN several proposals with mixed statuses
- WHEN a reviewer calls `GET /api/cmdb/proposals?status=DRAFT`
- THEN the response MUST include only DRAFT proposals
- AND MUST be paginated.

### REQ-CMAP-015: External HTTP and MCP exposure

The system MUST expose the proposal endpoints via plain HTTP under `/api/cmdb/proposals/*` for external clients. The system MUST also expose the same operations through an MCP server wrapper in v1 only if it does not duplicate the HTTP contract; otherwise HTTP alone is acceptable.

#### Scenario: External HTTP call succeeds end-to-end

- GIVEN a remote MCP/HTTP client with a bearer token carrying `AI_PROPOSE_CI`
- WHEN the client POSTs a valid manifest to `/api/cmdb/proposals`
- THEN the response MUST be HTTP 201 with a `proposal_id`, identical to the internal path.

### REQ-CMAP-016: DRAFT TTL auto-revokes stale proposals

The system MUST auto-transition `DRAFT → REVOKED` for any proposal whose `created_at` is older than 30 days. The system MUST emit a `CI_PROPOSAL_REVOKE` audit row with `actor_role="SYSTEM"` and MUST preserve the proposal node for audit replay.

#### Scenario: Stale DRAFT is auto-revoked

- GIVEN a DRAFT proposal with `created_at` 31 days old
- WHEN the TTL sweep runs
- THEN `:CIProposal.status` MUST equal `REVOKED`
- AND one `CI_PROPOSAL_REVOKE` audit row with `actor_role="SYSTEM"` MUST exist.

## Scenarios

See per-requirement scenarios above. Coverage: happy path (001, 003, 006), denial by guardrail (010, 011), denial by permission (004, 005), concurrent edit (008), revocation (007, 016), expired/TTL'd (016), malformed manifest (001), unknown category (002), CI id collision (009), secret redaction (013), read filtering (014), external exposure (015).

## Out of Scope

- Automatic CI discovery from documents, CSV, or incident payloads.
- Editing a proposal after submission; reviewers approve or revoke only.
- Bulk import (CSV/JSON).
- CI deletion, CI update, or relationship editing; v1 is creation-only.
- Real-time push (websocket/MQTT) for "new proposal pending".
- New business-rule validators (duplicate-IP, duplicate-label, category-must-exist at write time) — separate change.
- Per-category optional attribute registry; manifest stays flat `metadata: dict`.

## Dependencies

- `ai-chat-harness-guardrails` — extends the two-layer guard contract with `propose_ci` intent and `ci_proposal:<id>` target.
- `audit-logging` — adds `CI_PROPOSAL_*` event types and required context fields.
- `cmdb-categories` — Category catalog; manifest `category` resolves against `:Category.name` at submit and approve time.