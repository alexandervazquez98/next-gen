# Proposal: feat-cmdb-ai-handoff

> **TL;DR** — Enable AI agents (the internal `AIAgentConsole` and external clients via MCP/HTTP) to propose new Configuration Items (CIs) through a structured manifest, with a Human-In-The-Loop approval gate before any CI is committed to the CMDB graph. v1 ships the proposal lifecycle, a dedicated `/proposals/cmdb` review page, the two new permissions, the audit event types, and a docs guide that teaches an external agent how to compose a valid manifest and call the endpoints.

## Problem

Today the only path to create a CI is `POST /api/nodes` (`backend/routers/nodes.py:94-172`), which performs an immediate `MERGE (:CI {id: …})` in Neo4j. The `Node` model has **no draft, preview, or proposed state** (`backend/models/core.py:10-46`), the AI surface is read-only with a strict allowlist (`backend/services/node_service.py:25-50, :53-61`), and `docs/AI_AGENT_GUIDE.md:37-55` explicitly documents that AI agents cannot create CIs. Three concrete gaps:

1. **Agents cannot propose CIs.** No `create_ci` tool/intent exists; the only LLM path is `/api/ai/chat` with no harness intent for creation (`backend/services/ai_chat_service.py:608`).
2. **No pre-commit review.** Whatever an operator submits through `CIEditor` (`frontend/components/CIEditor.tsx:363`) is committed immediately — no diff, no approval.
3. **Audit gap on AI-vs-human provenance.** `audit_events` records `actor_role` (`AI_DIAGNOSTIC` / `AI_OPERATOR`) but no "this CI was proposed by agent X and approved by human Y" record exists.

## Why now

- The repo already encodes the **two-layer guard pattern** (`permission → guardrail → side effect`) in `openspec/specs/ai-chat-harness-guardrails/spec.md:1-100` and a **DRAFT→APPROVED→REVOKED lifecycle** in `openspec/specs/mqtt-mapping-lifecycle/spec.md` plus `backend/repositories/mqtt_mapping_repo.py:172-270, :386-507`. Both are direct precedents; re-inventing them would duplicate rather than compose.
- The CMDB write path is well-instrumented (`backend/services/node_service.py:150-188`, audit hooks at `backend/routers/nodes.py:43-55, :121-171`); adding a proposal layer requires no new audit primitives — only new event types.
- The **Category catalog is already live and dynamic** (`backend/routers/catalog.py:23-73` → `GET /api/categories`); a manifest can reference category names without static enums.
- Operators are blocked today: every new device onboarding requires a human in `CIEditor`. AI-assisted onboarding is impossible.
- Future changes (CSV/JSON bulk import, automatic CI discovery from documents) all need the same HITL primitive — this change is the foundation.

## Goals

- [ ] An AI agent with `AI_PROPOSE_CI` can submit a CI manifest and get back a `proposal_id` without touching the graph.
- [ ] A human reviewer with `CI_APPROVE_PROPOSAL` can list pending proposals, inspect a per-proposal diff against the live Category catalog, and approve (creates the CI) or revoke (no CI created, audit trail preserved).
- [ ] Every state transition emits exactly one audit row carrying `proposal_id`, `proposed_by`, `actor_role`, `previous_state`, `next_state`, `version`, and a redacted summary of the applied manifest.
- [ ] The two-layer guard contract is preserved: missing permission → HTTP 403; guardrail denial → HTTP 200 with `harness_result.denied=true`.
- [ ] `docs/CMDB_AI_MANIFEST.md` teaches an external agent the manifest schema, the two endpoints, and the review/approval semantics with worked examples.
- [ ] Existing `POST /api/nodes`, `DELETE /api/nodes/{id}`, and `PUT /api/nodes/{id}/metadata` remain unchanged (audit replay and `CIEditor` commits continue to work).

## Non-goals

- Automatic CI discovery from documents, CSV, or incident payloads (v1 only accepts chat-described manifests).
- Editing a proposal after submission; reviewers approve or revoke only.
- Bulk import (CSV/JSON).
- CI deletion, CI update, or relationship editing; v1 is creation-only.
- Real-time push of "new proposal pending" notifications; the badge is poll-based, matching the existing `useSystemStatusQuery` pattern (`frontend/hooks/queries/useSystemStatusQuery.ts:5-9`).
- New business-rule validators (duplicate-IP, duplicate-label, category-must-exist at write time) — separate change.

## Approach (high-level)

```
   AI agent                Backend                      Human reviewer
       │                       │                              │
       │ POST /api/cmdb/       │                              │
       │   proposals           │                              │
       │ (manifest JSON)──────▶│                              │
       │                       │ create :CIProposal           │
       │                       │ status=DRAFT, version=1      │
       │◀──── proposal_id ─────│                              │
       │                       │                              │
       │                       │◀── GET /api/cmdb/ ──────────│
       │                       │    proposals?status=DRAFT    │
       │                       │───── list w/ manifest ─────▶│
       │                       │                              │
       │                       │◀── POST .../proposals/{id}/ ─│
       │                       │    approve | revoke          │
       │                       │                              │
       │ on approve:           │                              │
       │  call existing        │                              │
       │  node_service.        │                              │
       │  create_update_node() │                              │
       │  + link (:CIProposal) │                              │
       │  -[:RESULTED_IN]->    │                              │
       │  (:CI)                │                              │
       │                       │────── audit row ────────────▶│
```

The CI commit path is **unchanged**: on `approve` the backend delegates to the existing `node_service.create_update_node()` so audit hooks, metric reconciliation, and category/hardware binding fire exactly as today.

## Product decisions (locked)

| # | Decision | Implication |
|---|----------|-------------|
| 1 | **Agent surface = internal `AIAgentConsole` + external MCP/HTTP, same core.** | One backend router (`/api/cmdb/proposals/*`) serves both; no separate internal path. |
| 2 | **HITL UX = dedicated review page at `/proposals/cmdb` + badge/shortcut in `AIAgentConsole`.** | New route in `frontend/App.tsx:229-246`; `AIAgentConsole.tsx:1-144` grows a `pendingProposals` count badge. |
| 3 | **Proposal source v1 = chat-described natural language, agent structures.** | No auto-discovery. Docs guide teaches the agent how to extract `id`, `label`, `category`, free-form attributes from prose. |
| 4 | **Lifecycle mirrors `MqttMetricMapping` — `DRAFT → APPROVED / REVOKED`, optimistic `version`, audit of applied vs original.** | Reuse the `mqtt-mapping-lifecycle` precedent, not re-derive. Version increments on every state transition. |

## Storage and lifecycle

A new Neo4j label `:CIProposal` keeps proposals **separate from `:CI`** so a DRAFT can never be confused with a live node:

```
(:CIProposal {
    id:                     String   // ULID/UUID; returned to the agent
    manifest_json:          String   // verbatim JSON the agent submitted
    applied_manifest_json:  String?  // manifest actually applied (may differ
                                     // if backend normalizes fields); null until APPROVED
    status:                 String   // DRAFT | APPROVED | REVOKED
    version:                Int      // 1 on create; +1 on every transition
    proposed_by:            String   // username
    proposed_role:          String   // role at submission time
    reviewed_by:            String?  // username of approver/revoker (null while DRAFT)
    reviewed_at:            DateTime?
    created_at:             DateTime
    updated_at:             DateTime
    resulted_ci_id:         String?  // populated only when APPROVED links to :CI
})

(:CIProposal)-[:PROPOSED_BY]->(:User)
(:CIProposal)-[:PROPOSED_FOR]->(:Category)   // CI.type / Category.name
(:CIProposal)-[:RESULTED_IN]->(:CI)          // only after APPROVED
```

State machine (mirrors `mqtt-mapping-lifecycle`):

```
       create                approve                  revoke
  ───────────────▶   DRAFT ────────────▶   APPROVED   (terminal)
                   (version=1)           (version=2)
                          │
                          │ revoke
                          ▼
                       REVOKED            (terminal)
                       (version=2)
```

- `create` → status=DRAFT, version=1.
- `approve` (only from DRAFT) → status=APPROVED, version=2, sets `reviewed_by/at`, `applied_manifest_json`, `resulted_ci_id`, creates the `:CI` via existing service, writes `(:CIProposal)-[:RESULTED_IN]->(:CI)`.
- `revoke` (from DRAFT or APPROVED) → status=REVOKED, version+=1, sets `reviewed_by/at`. **No** `:CI` created when revoking from DRAFT; if revoking from APPROVED, the `:CI` already exists and stays (the proposal link is updated to indicate revocation, not deletion).

## Manifest schema

The manifest is a JSON object mirroring the live `Node` shape (`backend/models/core.py:10-46`) with `category` resolved against `GET /api/categories` at submission and at approve time:

```json
{
  "schema_version": 1,
  "ci": {
    "id":              "CI-N9X3K2",
    "label":           "Core Router Bogotá",
    "category":        "Router",                // MUST match a live :Category.name
    "brand":           "Cisco",
    "model":           "ASR-1000",
    "serialNumber":    "FOC1234X5YZ",
    "firmwareVersion": "17.09.01a",
    "ip":              "10.20.30.1",
    "owner":           "NOC-LATAM",
    "location_name":   "Bogotá DC-1",
    "status":          "OK",
    "pollingInterval": 60,
    "metadata":        { "rack": "R12", "role": "edge" },
    "snmp":            { "version": "v2c", "community": "<REDACTED-IN-AUDIT>" }
  },
  "rationale":   "Spoke router for Bogotá DC upgrade; brand/model from procurement sheet.",
  "source_refs": ["chat:msg-2026-09-13-001"]
}
```

- `ci.category` MUST equal an existing `:Category.name`; backend re-validates at submit and at approve.
- Free-form `metadata` keys allowed but cannot override blocked AI fields (`backend/services/node_service.py:25-50`).
- A per-category optional-attribute registry is **out of v1** (Open Questions §15.7).

## Permissions and roles

Two new permission members, added to both `AIPermission` and `UserPermission` enums (`backend/models/user.py:16-26, :28-58`):

| Permission enum member | Type | Description |
|------------------------|------|-------------|
| `AI_PROPOSE_CI` | `AIPermission` | Bearer may submit a CI manifest via `POST /api/cmdb/proposals`. |
| `CI_APPROVE_PROPOSAL` | `UserPermission` | Bearer may approve or revoke via `POST /api/cmdb/proposals/{id}/approve` and `/revoke`. |

Seed changes (`backend/seed_roles.py:57-81`):

| Role | Added permission |
|------|------------------|
| `ADMIN` (already gets all `UserPermission`) | `CI_APPROVE_PROPOSAL` |
| `OPERATOR` | `CI_APPROVE_PROPOSAL` |
| `AI_DIAGNOSTIC` | `AI_PROPOSE_CI` |
| `AI_OPERATOR` | `AI_PROPOSE_CI` |

`CI_APPROVE_PROPOSAL` is **never** granted to any `AI_*` role in v1 — humans always have the final say on commit. The split mirrors the existing `CI_EDIT` (human) vs `AI_CI_UPDATE_METADATA` (AI metadata subset) pattern.

## Affected areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/routers/cmdb_proposals.py` | New | HTTP routes `POST /api/cmdb/proposals`, `GET /api/cmdb/proposals`, `GET /api/cmdb/proposals/{id}`, `POST .../approve`, `POST .../revoke`. |
| `backend/services/cmdb_proposal_service.py` | New | Create / list / approve / revoke orchestrator; on approve calls existing `node_service.create_update_node()`. |
| `backend/repositories/cmdb_proposal_repo.py` | New | Neo4j writer for `:CIProposal`; parameterized Cypher; optimistic-version check. |
| `backend/models/core.py` | Modified | Add `CIProposal` Pydantic model + `ManifestPayload` + per-state validation. |
| `backend/models/user.py:16-26, :28-58` | Modified | Add `AI_PROPOSE_CI` and `CI_APPROVE_PROPOSAL` enum members. |
| `backend/seed_roles.py:57-81` | Modified | Seed `AI_PROPOSE_CI` on `AI_*` roles; `CI_APPROVE_PROPOSAL` on `OPERATOR` (ADMIN gets all). |
| `backend/services/ai_guard_service.py` | Modified | Add `ci_propose` cooldown key + bulk threshold (>5 proposals/hour from one agent → escalate/deny), mirroring `ci_metadata_update` cooldown (`:28-33`). |
| `backend/services/audit_service.py` | Modified | Add `CI_PROPOSAL_CREATE`, `CI_PROPOSAL_APPROVE`, `CI_PROPOSAL_REVOKE` event types. |
| `backend/routers/ai.py:308-619` | Modified (optional) | New `intent=create_ci_proposal` could route chat-described creation through the harness; out of v1 if PR budget tight (Open Questions §15.5). |
| `backend/migrations/005_ci_proposal_schema.cypher` | New | Constraint: `(:CIProposal.id)` unique; index `(status, created_at)`. |
| `frontend/pages/ProposalsCmdbPage.tsx` | New | List + detail-diff view at route `/proposals/cmdb`. |
| `frontend/components/AIAgentConsole.tsx:1-144` | Modified | Pending-proposals count badge + deep-link to review. |
| `frontend/App.tsx:229-246` | Modified | Register `/proposals/cmdb` route. |
| `frontend/services/api.ts`, `services/queryResources.ts` | Modified | New `cmdbProposals` query keys + API wrappers. |
| `docs/CMDB_AI_MANIFEST.md` | New | Agent-facing guide: prompt template, manifest schema, endpoint contract, examples. |
| `docs/AI_AGENT_GUIDE.md:37-55` | Modified | Add CI proposal row to the capability table; link to new guide. |
| `openspec/changes/feat-cmdb-ai-handoff/specs/cmdb-ai-proposals/spec.md` | New | Spec for the proposal lifecycle + endpoints + permissions. |
| `openspec/changes/feat-cmdb-ai-handoff/specs/cmdb-proposal-review-ui/spec.md` | New | Spec for the `/proposals/cmdb` review page UX. |
| `openspec/specs/ai-chat-harness-guardrails/spec.md` (delta) | Modified | Add `propose_ci` intent + cooldown key + guard target. |
| `openspec/specs/audit-logging/spec.md` (delta) | Modified | Add `CI_PROPOSAL_*` event types and required context fields. |
| `backend/tests/test_cmdb_proposals.py` | New | TDD coverage per `openspec/config.yaml:14-19`. |
| `frontend/components/__tests__/ProposalsCmdbPage.test.tsx` | New | Component + diff rendering tests. |

## Risks and mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Agent proposes an `id` that collides with an existing `:CI`; `MERGE` silently overwrites. | Medium | Backend rejects proposals whose `ci.id` already exists on `:CI` with HTTP 409; reviewer sees a "collision" badge in the diff view. |
| Category renamed/deleted between draft and approve. | Medium | Backend re-validates `category` against the live `Category` list at approve time; failure surfaces as a denied approve with a structured reason; audit row still emitted. |
| AI bulk-proposes many CIs before any human sees them. | Medium | Extend `ai_guard_service.check_bulk_detection` with `propose_ci` key (>5 proposals/hour from one agent → escalate/deny); same pattern as `ci_metadata_update` cooldown. |
| Reviewer approves a stale proposal (graph drifted since draft). | Low | Diff view shows current Category list and any collision/conflict at approve time; reviewer sees "X CIs added/changed since this proposal was opened". |
| Two reviewers approve the same proposal concurrently. | Low | Optimistic `version` + `MATCH (p:CIProposal {id: $id, version: $v}) SET …` — first writer wins, second gets HTTP 409. |
| External MCP client submits a manifest that includes secrets (`snmp.community`). | Medium | `applied_manifest_json` redacts secret fields at audit time (see Open Questions §15.4); never log raw payloads; docs explicitly warn against sending credentials. |
| Audit table grows large with proposal churn. | Low | `CI_PROPOSAL_CREATE` rows are lower priority than `CI_PROPOSAL_APPROVE` for retention; defer retention policy to ops. |
| Scope creep — accidental modification of `POST /api/nodes`. | Medium | Code review rule + e2e test that asserts `POST /api/nodes` behavior is unchanged. |

## First-slice scope (v1 PR minimum)

1. `:CIProposal` schema + migration with constraints.
2. Endpoints `POST /api/cmdb/proposals`, `GET /api/cmdb/proposals`, `GET /api/cmdb/proposals/{id}`, `POST /api/cmdb/proposals/{id}/approve`, `POST /api/cmdb/proposals/{id}/revoke`.
3. Service layer that calls existing `node_service.create_update_node()` on approve (no duplication of the CI write path).
4. Two new permissions (`AI_PROPOSE_CI`, `CI_APPROVE_PROPOSAL`) seeded into `AI_*` and `OPERATOR`/`ADMIN` roles.
5. Audit event types `CI_PROPOSAL_CREATE`, `CI_PROPOSAL_APPROVE`, `CI_PROPOSAL_REVOKE` with required context.
6. AI guard `ci_propose` cooldown + bulk threshold.
7. New frontend route `/proposals/cmdb` with list + detail-diff view.
8. Pending-proposals badge in `AIAgentConsole`.
9. New docs `docs/CMDB_AI_MANIFEST.md` + update to `docs/AI_AGENT_GUIDE.md`.
10. Tests per `openspec/config.yaml:14-19` strict TDD: pytest backend + Vitest frontend.

## Out of scope (deferred)

| Item | Reason |
|------|--------|
| Automatic CI discovery from documents / CSV / incidents | No validated demand yet; future change builds on this HITL primitive. |
| Edit a proposal after submission | Simplifies audit reasoning and avoids diff-vs-diff UX. |
| Bulk import (CSV/JSON) | Different reviewer flow (per-row diff vs per-manifest diff); deferred. |
| CI deletion, update, or relationship editing | v1 is creation-only; mutation flows get their own HITL when prioritized. |
| `intent=create_ci_proposal` in `/api/ai/chat` harness | Optional; can be added later without breaking the proposal endpoint contract. |
| Real-time push (websocket/MQTT) for "new proposal pending" | Polling matches the existing `useSystemStatusQuery` pattern; lower risk. |
| Per-category optional attribute registry | Empty in v1; manifest stays flat `metadata: dict`. |

## Open questions for spec phase

1. **Conflict semantics on concurrent approval**: 409 (optimistic-version) or soft warning that lets the second approval overwrite? (Lean: 409.)
2. **TTL on DRAFT proposals**: auto-expire after N days? (Lean: 30 days → auto-REVOKED, audit row kept.)
3. **Audit retention**: do `CI_PROPOSAL_*` rows share the existing retention policy, or a stricter one? (Open — defer to ops.)
4. **Manifest secret redaction**: which fields are redacted in `applied_manifest_json`? (Lean: `snmp.community`, `snmp.authKey`, anything matching `*key|*token|*secret|*password`.)
5. **Chat harness integration**: add a `create_ci_proposal` intent in v1, or keep it strictly endpoint-driven? (Lean: out of v1 to keep PR small.)
6. **Who can revoke**: only the original approver, any user with `CI_APPROVE_PROPOSAL`, or both? (Lean: any user with `CI_APPROVE_PROPOSAL` while status=DRAFT; only ADMIN while status=APPROVED.)
7. **Per-category optional attributes**: add a small registry now, or defer entirely? (Lean: defer; manifest stays flat.)
8. **MCP server exposure**: v1 needs a thin MCP wrapper, or is HTTP enough? (Lean: HTTP only; MCP can wrap the same endpoints later.)

## Capabilities (contract with sdd-spec)

### New Capabilities
- `cmdb-ai-proposals`: The CI proposal lifecycle — manifest submission, DRAFT/APPROVED/REVOKED state machine, audit, CI commit on approve. Owns endpoints under `/api/cmdb/proposals/*`, the `:CIProposal` schema, and `AI_PROPOSE_CI` permission semantics.
- `cmdb-proposal-review`: The human review surface at `/proposals/cmdb` — list, detail diff, approve/revoke controls, and the pending-count badge in `AIAgentConsole`.

### Modified Capabilities
- `ai-chat-harness-guardrails`: Add the `propose_ci` intent slot, the `ci_propose` cooldown key, and the guard target `ci_proposal:<proposal_id>` — preserving the existing two-layer (403 / 200-with-denied) contract.
- `audit-logging`: Add `CI_PROPOSAL_CREATE`, `CI_PROPOSAL_APPROVE`, `CI_PROPOSAL_REVOKE` event types and the required context fields (`proposal_id`, `proposed_by`, `actor_role`, `previous_state`, `next_state`, `version`, `applied_manifest_summary`).

## Rollback Plan

- All new code lands behind new routes, new permission members, and a new Neo4j label. Disabling the feature = (1) revoking `AI_PROPOSE_CI` from `AI_*` roles in `seed_roles.py`, (2) revoking `CI_APPROVE_PROPOSAL` from `OPERATOR`/`ADMIN`, (3) removing the `/proposals/cmdb` route from `App.tsx`. Existing `POST /api/nodes` and the audit pipeline remain untouched.
- `:CIProposal` nodes can be left in Neo4j (no destructive cleanup) or removed with a one-off Cypher deletion if the change is permanently reverted. Already-approved proposals stay linked to their `:CI` via `:RESULTED_IN`; deleting the proposal does not cascade to the CI.

## Success Criteria

- [ ] An AI agent can submit a CI manifest via `POST /api/cmdb/proposals` and receive a `proposal_id` within 200 ms p95 (mocked Neo4j).
- [ ] A human reviewer can list, inspect, approve, and revoke proposals end-to-end through the new UI.
- [ ] Audit replay shows exactly one row per state transition carrying the required context; no rows leak secrets.
- [ ] `pytest backend/tests/test_cmdb_proposals.py` passes; Vitest passes; strict TDD per `openspec/config.yaml:14-19` honored.
- [ ] Existing `POST /api/nodes`, `DELETE /api/nodes/{id}`, `PUT /api/nodes/{id}/metadata` behavior is unchanged (regression tests green).
- [ ] `docs/CMDB_AI_MANIFEST.md` is sufficient for an external agent to compose a valid manifest without further prompting.
- [ ] PR stays within `review_budget_changed_lines: 400` budget or is split into chained PRs per `openspec/config.yaml:27`.