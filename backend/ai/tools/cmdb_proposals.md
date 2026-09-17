# CMDB Proposal Tools (Human-in-the-Loop)

Structured manifest submission for AI agents that need to add new
Configuration Items (CIs) to the NEX-GEN CMDB. AI agents MUST NOT call
`POST /api/nodes` directly — every CI goes through a human-approved
proposal flow with optimistic-version concurrency control.

## Purpose

When an operator describes new CIs in chat, the agent structures them
into a JSON manifest and submits it via the MCP tools below. The
proposal lands in `DRAFT` state until a human with `CI_APPROVE_PROPOSAL`
reviews it at `/proposals/cmdb` and either approves or revokes.

## Lifecycle states

| State | Meaning | Who transitions |
|-------|---------|-----------------|
| `DRAFT` | Submitted, awaiting human review | Created by `propose_ci` |
| `APPROVED` | Applied to the CMDB graph (CI was created) | Set by `approve_proposal` |
| `REVOKED` | Rejected, cancelled, or TTL-expired | Set by `revoke_proposal` or TTL sweep |

Every transition carries an optimistic `version` integer. Concurrent
edits fail with `409 version_conflict`; the agent must refetch and retry.

## MCP tools

All four tools live behind `/api/cmdb/proposals/*` and the MCP wrapper
in `backend/mcp/cmdb_proposal_server.py`. The agent invokes them with
JSON arguments; the backend executes and returns provider-neutral JSON.

### `propose_ci(manifest)` — submit a new proposal

Use when the operator describes new CIs to add to the CMDB.

```json
{
  "manifest": {
    "summary": "Onboard POP-CENTRAL router and switch",
    "cis": [
      {
        "id": "edge-router-pop-central",
        "type": "Router",
        "name": "edge-router-pop-central",
        "ip": "10.0.0.1",
        "attributes": {
          "vendor": "Mikrotik",
          "model": "CCR2216",
          "location": "pop-central"
        }
      }
    ]
  }
}
```

Returns `201` with `proposal_id` and `version`. The proposal is `DRAFT`
until reviewed.

### `list_proposals(filters)` — list proposals with filters

Use when the operator asks for pending, approved, or revoked proposals.

```json
{
  "filters": {
    "status": "DRAFT",
    "category": "Router",
    "proposed_by": "ai-bot",
    "page": 1,
    "page_size": 50
  }
}
```

Returns `{ rows: [...], total: N, page: 1, page_size: 50 }`.

### `approve_proposal(id, body)` — apply a DRAFT proposal

Use when a human operator confirms the proposal should be applied. The
backend delegates to `node_service.create_update_node()`, so the audit
trail is identical to a manually-created CI.

```json
{
  "id": "prop-abc-123",
  "body": {
    "version": 1,
    "expected_category": "Router"
  }
}
```

Returns the resulting CI id. Concurrent edits return `409` — refetch and
retry with the new version.

### `revoke_proposal(id, body)` — cancel a proposal

Use when a human rejects a proposal or wants to cancel their own pending
submission.

```json
{
  "id": "prop-abc-123",
  "body": {
    "version": 1,
    "reason": "duplicate of CI-456"
  }
}
```

Returns the new `REVOKED` state. Only `DRAFT` and `APPROVED` proposals
can be revoked; already-`REVOKED` returns `409`.

## Manifest schema

The `manifest.cis[]` array is the heart of the proposal. Each element:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Unique CI id within the CMDB; kebab-case recommended |
| `type` | string | yes | Must match a live `:Category` from `GET /api/categories` |
| `name` | string | yes | Display name |
| `ip` | string | no | IPv4/IPv6 if applicable |
| `attributes` | object | no | Type-specific attributes; only fields allowed for the category |

### Secret-like fields — NEVER include plain text

Community strings, passwords, tokens, and similar secrets MUST be
referenced, not embedded:

```json
{
  "id": "switch-core-01",
  "type": "Switch",
  "name": "switch-core-01",
  "attributes": {
    "snmp_community_ref": "secret://pop-central/snmp/ro",
    "location": "datacenter-1"
  }
}
```

The audit walker (`redact_manifest_secrets` in
`backend/services/audit_service.py`) drops plain-text secrets from audit
logs but the agent should not embed them at all.

### Duplicate-id collision

If another CI already uses the proposed `id`, `propose_ci` returns
`409 id_collision`. The agent must:
1. Inform the operator that the id is taken.
2. Suggest an alternative id (suffix `-2`, `-new`, or rename).
3. Ask the operator to confirm before resubmitting.

### Category drift

`type` is resolved against the live `:Category` list at approval time.
If a category was renamed or deleted between proposal and approval, the
backend returns `409 category_drift`. The agent must refetch
`/api/categories` and update the manifest.

## Permission matrix

| Tool | Permission required |
|------|---------------------|
| `propose_ci` | `AI_PROPOSE_CI` |
| `list_proposals` | `CI_VIEW` (or `AI_VIEW_ALL` for AI agents) |
| `approve_proposal` | `CI_APPROVE_PROPOSAL` AND `CI_EDIT` |
| `revoke_proposal` | `CI_APPROVE_PROPOSAL` |

Missing permission returns `403 missing_permission: <perm> required`.

**Separation of duties**: an AI agent that submits a proposal via
`propose_ci` MUST NOT also call `approve_proposal` for the same proposal,
even if its token carries `CI_APPROVE_PROPOSAL`. The review gate exists
because a human must validate AI-generated topology changes.

## HITL rules (non-negotiable)

1. **No direct graph writes.** `POST /api/nodes` returns `403` for AI
   tokens. Never try to bypass via custom HTTP clients.
2. **One proposal per operator request.** If the operator describes
   five CIs, emit one manifest with `cis.length == 5`, not five separate
   proposals. Grouping is easier to review.
3. **Ask before inventing.** If the operator's description is ambiguous
   (e.g. "add the new server" with no IP, vendor, or location), ASK.
   Never fabricate CI attributes.
4. **Surface errors verbatim.** When a tool returns `4xx` with
   `errors[]` or `detail.reason`, quote the message back to the operator
   in plain language. Do not paraphrase or hide the reason.
5. **Respect the cooldown.** `propose_ci` is rate-limited via
   `ai_guard_service.propose_ci` (60s cooldown per agent, ≥5/h escalates
   to soft block). Wait and retry — do not spin in a tight loop.
6. **Version conflicts are expected.** When `approve_proposal` returns
   `409 version_conflict`, the operator or another reviewer updated the
   proposal. Refetch via `list_proposals` and ask the operator to
   reconfirm with the new version.

## Error handling cheat-sheet

| HTTP | Reason | Agent action |
|------|--------|--------------|
| `200` | `harness_result.denied=true` | Tell operator the guardrail blocked it. Do not retry with the same payload. |
| `403` | `missing_permission: X` | Tell operator the token lacks `X`. Do not retry. |
| `409` | `id_collision` | Suggest alternative id. Ask operator. |
| `409` | `version_conflict` | Refetch via `list_proposals`. Ask operator to reconfirm. |
| `409` | `category_drift` | Refetch `/api/categories`. Update manifest. |
| `422` | `invalid_manifest` with `errors[]` | Show errors. Ask operator to fix the manifest. |
| `429` | `cooldown_active` or `bulk_threshold` | Wait the cooldown seconds and retry once. |
| `500` | `ci_commit_failed` | Surface the error. Do not retry — likely operator input or DB issue. |

## Out of scope (for the agent)

- **Editing proposals** — once submitted, the agent cannot modify the
  manifest. If the operator wants changes, submit a NEW proposal.
- **CI updates** — modifying existing CIs is not via this tool. Use the
  metadata-allowlist write path (`PUT /metadata` with 5 allowed fields)
  when the operator asks for a non-structural change.
- **Bulk import** — CSV/JSON bulk import is a separate workflow with a
  different audit profile.
- **CI deletion** — not exposed in v1.
- **Relationship editing** — `(:CI)-[:HOSTED_IN]->(:Site)` etc. are
  managed through the graph topology editor, not via proposals.

## Provider boundary

These tools are not tied to Gemma, Gemini, LM Studio, or any provider-
native function-calling format. Backend code executes the tool and the
result is appended as provider-neutral chat context. The agent treats
each tool as a JSON-in/JSON-out function call.

The full worked example for an end-to-end flow lives at
`docs/ai/cmdb-proposals.md` (operator-facing reference). This file is
the agent-facing contract.