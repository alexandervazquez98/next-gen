# Design: feat-cmdb-ai-handoff

## Overview

**Problem.** The CMDB write path is a single immediate `MERGE (:CI {id: …})` (`backend/repositories/topology_repo.py:62-101`, `backend/routers/nodes.py:94-172`). AI agents have **no proposal surface** — `backend/services/ai_chat_service.py:608` exposes only `event_list`/`active_events`/`availability_check*` intents, and `docs/AI_AGENT_GUIDE.md:37-55` documents that CIs cannot be created by AI. There is no draft, no diff preview, and no Human-In-The-Loop gate, so today every new CI requires a human to click `COMMIT TO CMDB` in `frontend/components/CIEditor.tsx:363`.

**Approach.** Introduce a `:CIProposal` Neo4j label, a five-endpoint HTTP surface under `/api/cmdb/proposals/*`, and an MCP server wrapper that re-uses the same service layer. AI agents with `AI_PROPOSE_CI` submit a versioned manifest; a `:CIProposal` is created in `DRAFT` (optimistic `version=1`); a human reviewer with `CI_APPROVE_PROPOSAL` inspects a per-proposal diff against the live Category catalog and either approves (delegating to existing `node_service.create_update_node()`) or revokes. Every transition emits exactly one audit row (`CI_PROPOSAL_CREATE` / `CI_PROPOSAL_APPROVE` / `CI_PROPOSAL_REVOKE`) carrying redacted manifest data, honoring the two-layer guard contract from `openspec/specs/ai-chat-harness-guardrails/spec.md` (403 → forbidden, 200 + `harness_result.denied=true` → conversational deny). The CI commit path is **unchanged** — approval delegates to the existing write path so metric reconciliation, category/hardware relationships, default PING metric, and the `CI_CREATE_OR_UPDATE` audit hook all fire exactly as today.

## Goals & Non-goals

**Goals.** Ship the proposal lifecycle (DRAFT/APPROVED/REVOKED), two new permissions (`AI_PROPOSE_CI`, `CI_APPROVE_PROPOSAL`), audit event types, AI guard `propose_ci` cooldown + bulk threshold, the `/proposals/cmdb` review page, the pending-count badge in `AIAgentConsole`, MCP server wrapper, and `docs/CMDB_AI_MANIFEST.md`. Honor all 36 REQs across `cmdb-ai-proposals` (16), `ai-chat-harness-guardrails` delta (5), `audit-logging` delta (5), and `cmdb-proposal-review-ui` (10).

**Non-goals (testable boundaries).** No edit-after-submit (REQ-CMPR spec says approve/revoke only); no CSV/JSON bulk import; no CI deletion/update/relationship editing via this path; no `intent=create_ci_proposal` in `/api/ai/chat` (deferred per proposal §15.5); no websocket push of new proposals (polled via `useSystemStatusQuery` cadence); no per-category attribute registry (manifest stays flat `metadata: dict`).

## High-level architecture

```
            ┌────────────────────┐                ┌──────────────────────┐
 AIAgent    │  POST /api/cmdb/   │  validate      │ cmdb_proposal_service │
 Console ──▶│  proposals         │───────────────▶│ .create_proposal()    │
 (React)    │  (HTTP, JWT cookie)│                │   ├─ permission gate │
            └────────────────────┘                │   ├─ ai_guard gate   │
            ┌────────────────────┐                │   ├─ category resolve│
 MCP client │  propose_ci tool   │                │   ├─ repo.create()   │
 (external) │  (bearer token)    │───────────────▶│   └─ audit CREATE    │
            └────────────────────┘                │ .approve_proposal()  │
            ┌────────────────────┐                │   ├─ optimistic ver  │
 Reviewer   │  /proposals/cmdb   │  detail/list   │   ├─ category re-check│
 (React)    │  (HTTP, JWT cookie)│───────────────▶│   ├─ node_service.   │
            └────────────────────┘                │   │  create_update_  │
                                                 │   │  node() (existing)│
                                                 │   ├─ :RESULTED_IN    │
                                                 │   └─ audit APPROVE   │
                                                 └────────┬─────────────┘
                                                          │
                            Neo4j ◀─────── cmdb_proposal_repo (Cypher)
                            :CIProposal ─[:PROPOSED_BY]─▶ :User
                                       ─[:PROPOSED_FOR]─▶ :Category
                                       ─[:RESULTED_IN]───▶ :CI  (only APPROVED)
```

**Component list.**
- **Frontend.** `frontend/components/cmdb/proposals/{ProposalList,ProposalDetail,ProposalDiffView,ProposalActions,ProposalAuditTimeline,ProposalBadge}.tsx`, `frontend/pages/ProposalsCmdbPage.tsx`, `frontend/hooks/queries/useProposalsQuery.ts`, `useApproveProposal.ts`, `useRevokeProposal.ts`, `useProposalCountQuery.ts`; modify `frontend/App.tsx:229-246` (new route) and `frontend/components/AIAgentConsole.tsx:1-144` (badge near input).
- **Backend services.** `backend/services/cmdb_proposal_service.py` (orchestrator), extend `backend/services/ai_guard_service.py:28-33` (add `propose_ci` cooldown key + bulk threshold hook), `backend/services/audit_service.py` (add `CI_PROPOSAL_*` event types + manifest-redaction helper), `backend/services/category_icons.py` (no change; reuse `catalog_service.get_categories()`).
- **Repositories.** New `backend/repositories/cmdb_proposal_repo.py`; reuse `backend/repositories/topology_repo.py:62-101` for the actual `:CI` write via `node_service.create_update_node()`.
- **MCP server.** New `backend/mcp/cmdb_proposal_server.py` exposing `propose_ci`/`list_proposals`/`approve_proposal`/`revoke_proposal` as MCP tools that call the service layer directly (no HTTP loopback).

## Backend design

### New endpoints under `/api/cmdb/proposals`

| Method | Path | Auth | Permission | Status codes |
|---|---|---|---|---|
| `POST` | `/api/cmdb/proposals` | JWT (cookie or `Bearer`) | `AI_PROPOSE_CI` (or human with `CI_EDIT`) | 201, 200+denied, 400, 403, 409, 422 |
| `GET` | `/api/cmdb/proposals` | JWT | `CI_VIEW` | 200, 401, 403 |
| `GET` | `/api/cmdb/proposals/{id}` | JWT | `CI_VIEW` | 200, 401, 403, 404 |
| `POST` | `/api/cmdb/proposals/{id}/approve` | JWT | `CI_APPROVE_PROPOSAL` | 200, 401, 403, 404, 409 |
| `POST` | `/api/cmdb/proposals/{id}/revoke` | JWT | `CI_APPROVE_PROPOSAL` | 200, 401, 403, 404, 409 |

**Request schema (POST create).** `ManifestPayload` Pydantic model with `schema_version: int = 1`, `ci: Node`-shaped object (`id`, `label`, `category`, plus optional fields from `backend/models/core.py:10-46`), `rationale: str`, `source_refs: list[str]`. `category` resolved via `catalog_service.get_categories()` (REQ-CMAP-002). `metadata` keys cannot override `BLOCKED_AI_UPDATE_FIELDS` (`backend/services/node_service.py:27-38`).

**Response schema (201).** `{"proposal_id": "<uuid>", "status": "DRAFT", "version": 1, "created_at": iso8601, "resulted_ci_id": null}`. Detail endpoint additionally returns `applied_manifest_json`, `manifest_json`, `proposed_by`, `reviewed_by`, `reviewed_at`, plus `live_ci_diff` (added/changed/removed fields vs current `:CI` if it exists).

**Errors.** 403 (`{detail, reason:"missing_permission"}`), 422 (Pydantic + reason like `unknown_category` / `invalid_manifest`), 409 (`{detail, reason:"ci_id_collision" | "version_conflict" | "category_renamed"}`), 200 with `{"harness_result": {"denied": true, "status": "denied", "reason": "...", "reason_code": "cooldown_active"|"bulk_threshold"|"..."}}` per REQ-CMAP-011/REQ-AICHG-005.

### Service layer — `backend/services/cmdb_proposal_service.py`

Orchestrator pattern, mirroring the layered split in `backend/routers/nodes.py:94-172` ↔ `backend/services/node_service.py:150-188`:

1. **Permission gate.** `check_permission(UserPermission.CI_APPROVE_PROPOSAL, user)` for approve/revoke; `check_permission(AIPermission.AI_PROPOSE_CI, user)` (or `CI_EDIT` for humans via a separate path) for create. Failures raise `HTTPException(403)` and write `ACCESS_DENIED` audit.
2. **Guardrail gate** (create only). Calls `ai_guard_service.check_all_guards(ai_agent_id, "propose_ci", ["ci_proposal:new"])`. Reuses the in-memory cooldown cache at `ai_guard_service.py:47-97` and `check_bulk_detection` at `:303-375` with a lowered threshold (>5/h, configurable via env `CMDB_PROPOSAL_BULK_THRESHOLD=5`, default 5).
3. **Category resolve.** Pull live category names from `catalog_service.get_categories()`; reject if `ci.category` absent.
4. **CI id collision check.** `MATCH (ci:CI {id: $ci_id}) RETURN ci` before insert → 409 `ci_id_collision`.
5. **Repo call.** `cmdb_proposal_repo.create_draft(payload, proposer)` → returns `proposal_id`, `version=1`.
6. **Audit.** `record_critical_change(..., event_type="CI_PROPOSAL_CREATE", context={"proposal_id", "proposed_by", "actor_role", "previous_state": None, "next_state": "DRAFT", "version": 1, "applied_manifest_summary": redacted_manifest, ...})`.
7. **Operation log.** `ai_guard_service.record_operation(persona, agent_id, "propose_ci", "ci_proposal", proposal_id, label, "success"|"blocked"|"escalated", ...)`.

For `approve`: re-resolve category, re-check `:CI {id}` collision (could have been created concurrently), execute Cypher `MATCH (p:CIProposal {id: $id, version: $v}) SET p.status = 'APPROVED', p.version = $v + 1, ...`, then call existing `node_service.create_update_node(node_from_manifest, user)` (which already enforces `CI_EDIT`; CI_APPROVE_PROPOSAL holders in OPERATOR also need CI_EDIT — see Risk table below), then `MERGE (:CIProposal)-[:RESULTED_IN]->(:CI)`, write audit `CI_PROPOSAL_APPROVE`. If category missing or CI id collision at approve time → 409 with structured reason AND audit `CI_PROPOSAL_APPROVE` row with `outcome=VALIDATION_FAILURE` (REQ-CMAP-002 / REQ-AUDIT-004).

For `revoke`: same optimistic-version MATCH; status → `REVOKED`, version += 1, `reviewed_by`, `reviewed_at`. No `:CI` write when revoking from DRAFT; when revoking from APPROVED the `:CI` is preserved (REQ-CMAP-007 scenario 2). Audit `CI_PROPOSAL_REVOKE`.

### Repository layer — `backend/repositories/cmdb_proposal_repo.py`

Mirrors `backend/repositories/mqtt_mapping_repo.py:172-270` (`create_draft`) and `:386-507` (`approve`) but parameterizes all Cypher via `$params`. Key methods:

- `create_draft(proposal_id, manifest_json, applied_manifest_json=None, proposed_by, proposed_role, status="DRAFT", version=1) → dict`
- `get(proposal_id) → dict | None`
- `list(status=None, category=None, proposed_by=None, created_from=None, created_to=None, page=1, page_size=50) → (rows, total)`
- `approve(proposal_id, expected_version, reviewer_by, applied_manifest_json, resulted_ci_id) → dict` — uses `MATCH (p:CIProposal {id: $id, version: $v})` + `WHERE p.status = 'DRAFT'` so only one writer wins. Returns `None` if no match → service raises 409 `version_conflict`.
- `revoke(proposal_id, expected_version, reviewer_by, reason=None) → dict` — same pattern, allowed from DRAFT or APPROVED.
- `ttl_sweep(retention_days=30) → int` — `MATCH (p:CIProposal) WHERE p.status = 'DRAFT' AND p.created_at < datetime() - duration({days:$n}) SET p.status = 'REVOKED', p.version = p.version + 1, p.reviewed_by = 'SYSTEM', p.reviewed_at = datetime(), p.revoke_reason = 'ttl_expired' RETURN count(p)` (REQ-CMAP-016). Caller is responsible for emitting `CI_PROPOSAL_REVOKE` audit rows (one per swept node, `actor_role=SYSTEM`).

### MCP server — `backend/mcp/cmdb_proposal_server.py`

Thin wrapper that exposes four MCP tools calling the service layer **directly** (no HTTP loopback, matching `ai_guard_service` pattern of in-process invocation):

| Tool | Auth | Maps to |
|---|---|---|
| `propose_ci` | bearer with `AI_PROPOSE_CI` | `cmdb_proposal_service.create_proposal()` |
| `list_proposals` | bearer with `CI_VIEW` | `cmdb_proposal_repo.list()` |
| `approve_proposal` | bearer with `CI_APPROVE_PROPOSAL` | `cmdb_proposal_service.approve_proposal()` |
| `revoke_proposal` | bearer with `CI_APPROVE_PROPOSAL` | `cmdb_proposal_service.revoke_proposal()` |

`POST /api/cmdb/proposals/*` and the MCP server share the **same** service-layer entry points, so REQ-CMAP-015 ("external HTTP and MCP exposure…identical to the internal path") is satisfied.

### Permission additions

`backend/models/user.py:16-58` — append `AI_PROPOSE_CI = "AI_PROPOSE_CI"` to `AIPermission` and `CI_APPROVE_PROPOSAL = "CI_APPROVE_PROPOSAL"` to `UserPermission`. **Never** grant `CI_APPROVE_PROPOSAL` to any `AI_*` role in v1 (REQ-CMAP-005 scenario 2).

`backend/seed_roles.py:57-81`:

| Role | Add |
|---|---|
| `ADMIN` | (already gets all via `UserPermission` spread) |
| `OPERATOR` | `UserPermission.CI_APPROVE_PROPOSAL.value` |
| `AI_DIAGNOSTIC` | `AIPermission.AI_PROPOSE_CI.value` |
| `AI_OPERATOR` | `AIPermission.AI_PROPOSE_CI.value` |

Also extend `SYSTEM_ROLE_PERMISSION_UPGRADES` at `backend/seed_roles.py:6-17` so existing deployed roles pick up the new grants on next run (idempotent additive upgrade pattern already established at `:113-131`).

### Guardrail integration

Extend `backend/services/ai_guard_service.py:28-33`:

```python
COOLDOWNS["propose_ci"] = int(os.getenv("CMDB_PROPOSAL_COOLDOWN_SECONDS", "120"))  # mirrors ci_metadata_update
```

Cooldown target key: `ci_proposal:new` (pre-create) or `ci_proposal:<proposal_id>` (post-create) per REQ-AICHG-002. Add a `propose_ci` branch in `check_bulk_detection` that escalates/denies when same `ai_agent_id` has logged ≥5 successful `propose_ci` operations in the last 60 minutes (REQ-AICHG-004 / REQ-CMAP-010). Use a new env `CMDB_PROPOSAL_BULK_THRESHOLD=5` to keep the threshold in one place. Persist `AIOperationLog` rows with `operation="propose_ci"` exactly as today (`ai_guard_service.py:133-181`).

### Audit integration

Extend `backend/services/audit_service.py`:

1. Add new event types `CI_PROPOSAL_CREATE`, `CI_PROPOSAL_APPROVE`, `CI_PROPOSAL_REVOKE` (no enum today — `event_type` is a free `str` field on `AuditEvent`).
2. Extend `AUDIT_CONTEXT_ALLOWED_KEYS` (`audit_service.py:17-41`) with: `proposal_id`, `proposed_by`, `actor_role`, `previous_state`, `next_state`, `version`, `resulted_ci_id`, `applied_manifest_summary`, `applied_manifest_attributes`, `manifest_diff`, `revoke_reason`.
3. Add a new helper `redact_manifest_secrets(manifest: dict) -> dict` (separate from `sanitize_context`, which is allow-list and would drop the entire manifest). Walker uses regex on every key (case-insensitive) matching `*key|*token|*secret|*password`, plus explicit `snmp.community`, `snmp.authKey`, `snmp.privKey`, and replaces values with `"<REDACTED>"`. Walks nested `metadata`, `snmp`, and any other dict. (REQ-AUDIT-003 / REQ-CMAP-013.)
4. Approve events call `redact_manifest_secrets(node.model_dump())` to produce `applied_manifest_attributes`; create events call the same on the submitted manifest. Original raw values never logged.

## Frontend design

### Routes

`frontend/App.tsx:229-246` — add `<Route path="proposals/cmdb" element={<ProposalsCmdbPage />} />` and `<Route path="proposals/cmdb/:id" element={<ProposalsCmdbPage detailMode />} />`. Reuse `<ProtectedRoute>` already wrapping the `MainLayout`.

### Components (under `frontend/components/cmdb/proposals/`)

- `ProposalList.tsx` — table with columns `id`, `category`, `proposer`, `status`, `created_at`, `actions`. Server-side filter controls (status, category, proposer, date range) wired to query params. Empty state, loading skeleton, error banner per REQ-CMPR-008/009/010.
- `ProposalDetail.tsx` — orchestrator composing `ProposalDiffView`, `ProposalActions`, `ProposalAuditTimeline`.
- `ProposalDiffView.tsx` — side-by-side `manifest_json` vs live `:CI {id: ci.id}` state (added / changed / removed columns); "collision" badge when `:CI {id}` exists; "category drift" badge when `ci.category` no longer in `/api/categories` (REQ-CMPR-002).
- `ProposalActions.tsx` — Approve / Revoke buttons, gated on `hasPermission("CI_APPROVE_PROPOSAL")` (REQ-CMPR-006). Confirmation dialogs describe the resulting `:CI.id`. Toasts on success.
- `ProposalAuditTimeline.tsx` — vertical timeline fetched from `/audit?target_type=ci_proposal&target_id=<id>` reusing `AuditLogPage` query contract; falls back to embedded audit endpoint if needed (REQ-CMPR-005).
- `ProposalBadge.tsx` — small badge rendered near the chat input showing pending DRAFT count for the current user (REQ-CMPR-007).

### Hooks (`frontend/hooks/queries/`)

- `useProposalsQuery(filters)` — `useQuery` keyed on `["cmdb-proposals", filters]`, no `refetchInterval` (on-demand, opened by user).
- `useProposalDetailQuery(id)` — `useQuery` keyed on `["cmdb-proposals", "detail", id]`.
- `useProposalCountQuery()` — `useQuery` keyed on `["cmdb-proposals", "count", "draft"]` with `refetchInterval: 5000` (slower than `useSystemStatusQuery` 3s — matches REQ-CMPR-007 "at the existing cadence or slower").
- `useApproveProposal()` / `useRevokeProposal()` — `useMutation` that on success invalidates `["cmdb-proposals"]` (all), `["cmdb-proposals", "count", "draft"]`, `["nodes"]`, `["graph-topology"]`, `["audit"]`.

Add to `frontend/services/queryKeys.ts` (matches existing tuple-shape pattern at `:1-30`):

```typescript
cmdbProposals: (filters?: object) => ["cmdb-proposals", filters ?? {}] as const,
cmdbProposalDetail: (id: string) => ["cmdb-proposals", "detail", id] as const,
cmdbProposalDraftCount: () => ["cmdb-proposals", "count", "draft"] as const,
```

### AIAgentConsole integration

`frontend/components/AIAgentConsole.tsx:1-144` — add `<ProposalBadge />` next to the `MODEL: NexCO-Gen1` label (top-right of the console header). The badge deep-links to `/proposals/cmdb?status=DRAFT`. Hidden when count is 0.

### Service wrapper

`frontend/services/cmdbProposals.ts` — typed wrapper:

```typescript
export const fetchProposals = (filters, signal) => api.get<ProposalListResponse>(...)
export const fetchProposal = (id, signal) => api.get<ProposalDetailResponse>(...)
export const fetchProposalDraftCount = (signal) => api.get<{count: number}>("/cmdb/proposals/count?status=DRAFT", ...)
export const approveProposal = (id, body) => api.post<{status:"APPROVED", version:number, resulted_ci_id:string}>(`/cmdb/proposals/${id}/approve`, body)
export const revokeProposal = (id, body) => api.post<{status:"REVOKED", version:number}>(`/cmdb/proposals/${id}/revoke`, body)
```

### State management

Plain react-query only — **no** Redux/Zustand. The list/detail views are short-lived route components; cache keys per `queryKeys.cmdbProposals()`. Invalidate on mutation success.

### Permission-aware UI

`hasPermission("CI_APPROVE_PROPOSAL")` from `useAuth()` controls button visibility (REQ-CMPR-006). The list/diff/timeline remain read-only for everyone with `CI_VIEW`.

## Data model (Neo4j)

### `:CIProposal` label

Required properties: `id: String` (UUID v4), `manifest_json: String` (verbatim submitted JSON), `applied_manifest_json: String?` (post-normalization, null until APPROVED), `status: String` (`DRAFT|APPROVED|REVOKED`), `version: Int` (1 → 2 on first transition), `proposed_by: String`, `proposed_role: String`, `created_at: DateTime`, `updated_at: DateTime`, `resulted_ci_id: String?`, `revoke_reason: String?`.

### Relationships

- `(:CIProposal)-[:PROPOSED_BY]->(:User {username})`
- `(:CIProposal)-[:PROPOSED_FOR]->(:Category {name})`
- `(:CIProposal)-[:RESULTED_IN]->(:CI {id})` — only set on APPROVED (REQ-CMAP-006 scenario 1).

### Indexes & constraints

`backend/migrations/005_ci_proposal_schema.cypher` (additive, `IF NOT EXISTS` per `004_mqtt_metric_result_idempotency.cypher` style):

```cypher
CREATE CONSTRAINT ci_proposal_id_unique IF NOT EXISTS
FOR (p:CIProposal) REQUIRE p.id IS UNIQUE;
CREATE INDEX ci_proposal_status IF NOT EXISTS FOR (p:CIProposal) ON (p.status);
CREATE INDEX ci_proposal_created_at IF NOT EXISTS FOR (p:CIProposal) ON (p.created_at);
CREATE INDEX ci_proposal_category IF NOT EXISTS FOR (p:CIProposal) ON (p.proposed_category);
```

> **Not adding `(:CI {id})` constraint in this PR.** The repo's existing `topology_repo.upsert_node` (`backend/repositories/topology_repo.py:62-101`) relies on `MERGE` semantics; introducing a DB-level uniqueness constraint on `:CI.id` is out of scope and would break the Excel bulk-upload path (`backend/services/node_service.py:232-375`). The repository-layer collision check (`MATCH (:CI {id:$ci_id})`) at approve time already covers REQ-CMAP-009. Documented as a non-blocking observation for a future change.

### TTL/retention

Periodic sweep via `backend/scripts/cmdb_proposal_ttl_sweep.py` (new), scheduled by existing `cli_worker` or cron at 24h cadence. Calls `cmdb_proposal_repo.ttl_sweep(30)` and emits one `CI_PROPOSAL_REVOKE` audit row per swept node with `actor_role="SYSTEM"`, `revoke_reason="ttl_expired"` (REQ-CMAP-016). Sweep is idempotent — already-revoked nodes produce 0 audit rows.

## Manifest schema

```json
{
  "schema_version": 1,
  "ci": {
    "id":             "CI-N9X3K2",
    "label":          "Core Router Bogotá",
    "category":       "Router",
    "brand":          "Cisco",
    "model":          "ASR-1000",
    "serialNumber":   "FOC1234X5YZ",
    "firmwareVersion":"17.09.01a",
    "ip":             "10.20.30.1",
    "owner":          "NOC-LATAM",
    "location_name":  "Bogotá DC-1",
    "status":         "OK",
    "pollingInterval":60,
    "metadata":       {"rack":"R12","role":"edge"},
    "snmp":           {"version":"v2c","community":"<REDACTED-IN-AUDIT>"}
  },
  "rationale":   "Spoke router for Bogotá DC upgrade.",
  "source_refs": ["chat:msg-2026-09-13-001"]
}
```

Validation: `schema_version` MUST be int ≥ 1; `ci.id`, `ci.label`, `ci.category` required; `ci.category` MUST equal a live `:Category.name`; `ci.metadata` keys MUST NOT collide with `BLOCKED_AI_UPDATE_FIELDS`; `ci.id` MUST NOT collide with an existing `:CI.id`. Forward-compat: parser ignores unknown top-level fields under `ci` and unknown keys in `metadata`; bumping `schema_version` is the breaking-change signal.

## MCP tool contracts

| Tool | Input JSON Schema (excerpt) | Output | Errors |
|---|---|---|---|
| `propose_ci` | `{manifest: ManifestPayload, rationale?: string}` | `{proposal_id, status:"DRAFT", version:1, created_at}` | 401, 403 (`AI_PROPOSE_CI`), 422 (`unknown_category`/`invalid_manifest`), 409 (`ci_id_collision`), 200+denied (`cooldown_active`/`bulk_threshold`) |
| `list_proposals` | `{status?, category?, proposed_by?, created_from?, created_to?, page?, page_size?}` | `{rows: [...], total: int, page: int}` | 401, 403 |
| `approve_proposal` | `{id: string, version: int, expected_category?: string}` | `{status:"APPROVED", version:2, resulted_ci_id, applied_manifest_attributes}` | 401, 403, 404, 409 (`version_conflict`/`category_renamed`/`ci_id_collision`) |
| `revoke_proposal` | `{id: string, version: int, reason?: string}` | `{status:"REVOKED", version: int}` | 401, 403, 404, 409 (`version_conflict`) |

Auth: bearer token with `AI_PROPOSE_CI` (or appropriate user permission). Scope claim required: `{permissions: [...], scope: "cmdb.proposal"}`. Rate limit: 60 calls/min/token (`CMDB_PROPOSAL_RPM=60` env), 30/min/user — enforced in MCP middleware before reaching the service layer.

## Security & audit

### Permission matrix

| Caller role / perm | POST create | GET list/detail | POST approve | POST revoke |
|---|---|---|---|---|
| `ADMIN` | ✅ (admin all-perms) | ✅ | ✅ | ✅ |
| `OPERATOR` w/ `CI_APPROVE_PROPOSAL` | ✅ (CI_EDIT in seed) | ✅ | ✅ | ✅ |
| `VIEWER` | ❌ 403 | ✅ (CI_VIEW) | ❌ 403 | ❌ 403 |
| `AI_DIAGNOSTIC` w/ `AI_PROPOSE_CI` | ✅ (with guard) | ✅ (CI_VIEW via `AI_VIEW_ALL`) | ❌ 403 (NEVER `CI_APPROVE_PROPOSAL`) | ❌ 403 |
| `AI_OPERATOR` w/ `AI_PROPOSE_CI` | ✅ (with guard) | ✅ | ❌ 403 | ❌ 403 |
| Unauthenticated | ❌ 401 | ❌ 401 | ❌ 401 | ❌ 401 |

### Secret redaction list

Hard-coded deny list applied recursively before audit persistence: `snmp.community`, `snmp.authKey`, `snmp.privKey`, and any key matching regex `(?i).*(key|token|secret|password).*`. Applied to both `manifest_json` and `applied_manifest_json` snapshots. Test fixture in `backend/tests/test_audit_service.py` (new) asserts every match is `"<REDACTED>"`.

### Audit event shapes

```json
{
  "event_type":"CI_PROPOSAL_CREATE",
  "outcome":"SUCCESS",
  "actor_username":"ai-bot-bogota",
  "actor_role":"AI_OPERATOR",
  "target_type":"ci_proposal",
  "target_id":"<uuid>",
  "reason":"proposal_created",
  "context":{
    "proposal_id":"<uuid>",
    "proposed_by":"ai-bot-bogota",
    "actor_role":"AI_OPERATOR",
    "previous_state":null,
    "next_state":"DRAFT",
    "version":1,
    "applied_manifest_summary":{"id":"CI-N9X3K2","label":"Core Router Bogotá","category":"Router","snmp":{"version":"v2c","community":"<REDACTED>"}}
  }
}
```

`CI_PROPOSAL_APPROVE` carries `resulted_ci_id` and `applied_manifest_attributes` (live `:CI` properties). `CI_PROPOSAL_REVOKE` from TTL sweep carries `actor_role="SYSTEM"` and `revoke_reason="ttl_expired"` (REQ-AUDIT-001 scenario 3 / REQ-CMAP-016).

### Replay safety

Optimistic-version `MATCH (p {id, version:$v}) …` in both `approve` and `revoke` Cypher; first writer wins, second gets `None` row → service raises 409 `version_conflict`. No audit write on losing path (REQ-AUDIT-004 / REQ-CMAP-008).

### Threat model short-list

- **Prompt injection → manifest abuse.** Mitigation: `ci.category` resolve against live catalog; `ci.metadata` blocks `BLOCKED_AI_UPDATE_FIELDS` keys; `ci.id` collision check; secret redaction in audit.
- **Rogue AI token → bulk proposals.** Mitigation: `propose_ci` cooldown 120s; bulk threshold >5/h escalates/denies; `AIOperationLog` persistence.
- **Insider approving own AI proposals.** Mitigation: default role split — `AI_*` roles carry only `AI_PROPOSE_CI`, never `CI_APPROVE_PROPOSAL`; a human operator using their own credentials to create AND approve is acceptable (it's their identity, not the AI's).
- **Replayed approve POST.** Mitigation: optimistic `version` fails.
- **Secret leak via manifest.** Mitigation: `redact_manifest_secrets` walker; raw values never persisted or logged.

## Testing strategy (strict_tdd)

| Layer | What | File |
|---|---|---|
| Backend unit (repo) | `create_draft`, `get`, `list`, `approve`, `revoke`, `ttl_sweep` against a MagicMock Neo4j session | `backend/tests/test_cmdb_proposal_repo.py` |
| Backend unit (service) | Permission gate, guard gate, category resolve, collision, audit emission | `backend/tests/test_cmdb_proposal_service.py` |
| Backend unit (router) | 201/200/403/409/422 paths; MCP tool endpoints | `backend/tests/test_cmdb_proposal_router.py` |
| Backend unit (MCP) | Tool auth, schema validation, delegation | `backend/tests/test_mcp_cmdb_proposal_server.py` |
| Backend unit (audit) | Redaction walker, deny-list coverage, audit-row shape | `backend/tests/test_audit_redaction.py` |
| Backend unit (guard) | `propose_ci` cooldown + bulk threshold | extend `backend/tests/test_ai_guard_service.py` |
| Frontend unit | Component renders, permission gating, empty/loading/error states | `frontend/components/cmdb/proposals/__tests__/` |
| Frontend E2E (Playwright) | Submit → list → approve flow; revoke flow; badge deep-link | `frontend/e2e/cmdb-proposals.spec.ts` |

Every spec scenario from the four spec files maps to ≥1 test (REQs CMAP-001..016, AICHG-001..005, AUDIT-001..005, CMPR-001..010). Coverage target ≥85% on new modules (enforced by `cd backend && python -m pytest --cov=backend.services.cmdb_proposal_service --cov=backend.repositories.cmdb_proposal_repo --cov-fail-under=85`).

## Migrations & rollout

1. **Migration** — `backend/migrations/005_ci_proposal_schema.cypher` (constraint + 3 indexes, all `IF NOT EXISTS`).
2. **Permission seed migration** — extend `backend/seed_roles.py` (idempotent additive upgrade path already established).
3. **Rollout order** (matches chained-PR slices below): storage + service → MCP + HTTP → frontend list/detail → AIAgentConsole badge.
4. **Feature flag** — env `FEATURE_CMDB_PROPOSALS_ENABLED=false` (default off until first prod release). Gate all five HTTP endpoints and the MCP tools at the router/MCP entry point so unflagged deployments return 404.
5. **Rollback** — flip flag to false; remove `/proposals/cmdb` route from `App.tsx`; existing `:CIProposal` nodes are filtered out of all read queries by `status` and do not appear in topology views. Approved proposals keep their `:RESULTED_IN` link; rolling back does NOT cascade `:CI` deletion.

## Observability

- **Logs.** Structured JSON: `{"event":"cmdb_proposal.transition","proposal_id":"<uuid>","actor":"<user>","version_before":1,"version_after":2,"previous_state":"DRAFT","next_state":"APPROVED","ci_id":"CI-N9X3K2"}` emitted on every state change.
- **Metrics.** Counters `cmdb_proposal_created_total`, `cmdb_proposal_approved_total`, `cmdb_proposal_revoked_total` (tagged `actor_role`, `reason`); histogram `cmdb_proposal_approve_latency_seconds`; gauge `cmdb_proposal_draft_pending` (source: count of `(:CIProposal {status:'DRAFT'})`).
- **Alerts.** Bulk proposal rate > N/min (configurable, default 10) → page on-call; approve failure rate > 5% (5-min window) → page on-call.

## Open questions resolved

| # | Question | Resolution |
|---|---|---|
| 1 | Conflict semantics on concurrent approval | **409 `version_conflict`** via optimistic version (REQ-CMAP-008). |
| 2 | TTL on DRAFT | **30 days → auto-REVOKED** with `actor_role=SYSTEM` audit (REQ-CMAP-016). |
| 3 | Audit retention | **Share existing 90-day retention**; ops can tighten later via env (no change to `audit_service.AUDIT_RETENTION_DAYS`). |
| 4 | Manifest secret redaction | **`snmp.{community,authKey,privKey}` + regex `(?i).*(key|token|secret|password).*`** (REQ-AUDIT-003). |
| 5 | Chat harness integration | **Out of v1** — `intent=create_ci_proposal` not added; agents go through `/api/cmdb/proposals` directly. |
| 6 | Who can revoke | **Any holder of `CI_APPROVE_PROPOSAL`** — same set of users who can approve. No special ADMIN-only branch in v1 (simpler; matches `mqtt_mapping_repo` precedent). |
| 7 | Per-category optional attributes | **Deferred** — manifest stays flat `metadata: dict`. |
| 8 | MCP server exposure | **In** — user task spec requires the MCP wrapper. HTTP and MCP share the service layer. |

### Remaining open questions

- None blocking sdd-tasks. Optional follow-ups: (a) should `CI_APPROVE_PROPOSAL` be added to the `ADMIN` system-role upgrade list explicitly or rely on the spread of all `UserPermission`? (b) Should we add a `intent=create_ci_proposal` to `ai_chat_service.maybe_run_harness` in a follow-up slice to enable chat-described proposals end-to-end? (c) Should bulk threshold be lowered for new agents (cold start)?

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Agent `ci.id` collides with existing `:CI` | M | Repo pre-check → 409 `ci_id_collision`; UI badge in diff view (REQ-CMAP-009 / REQ-CMPR-002). |
| Category renamed between draft and approve | M | Re-resolve at approve time → 409 `category_renamed`; audit row still emitted (REQ-CMAP-002). |
| AI bulk-proposes before humans see any | M | `propose_ci` cooldown 120s + bulk threshold >5/h escalate/deny (REQ-AICHG-003/004). |
| Reviewer approves a stale proposal | L | Diff view shows current Category list + collision badge; TTL sweep covers abandoned drafts. |
| Concurrent approve race | L | Optimistic `version` in MATCH; first writer wins, second gets 409 (REQ-CMAP-008). |
| External MCP client sends secrets in `snmp` | M | `redact_manifest_secrets` walker before audit; docs warn explicitly; never log raw payloads (REQ-AUDIT-003). |
| Audit table grows with proposal churn | L | Share 90-day retention; lower priority for `CI_PROPOSAL_CREATE` rows (defer to ops). |
| Scope creep touches `POST /api/nodes` | M | Code review guardrail + regression tests in `backend/tests/test_routers_nodes.py` asserting unchanged behavior; service layer delegates to existing `node_service.create_update_node()`, never modifies it. |
| OPERATOR missing `CI_EDIT` after permission split | L | `OPERATOR` already has `CI_EDIT` in seed (`:39`); `CI_APPROVE_PROPOSAL` is added additive — no removal. |
| Feature flag forgotten in prod | L | Flag defaults to `false`; router returns 404 when off; deployment checklist step. |

## Work-unit breakdown hint (chained PRs)

The 36-REQ surface plus all new files (~14 new + 6 modified) would exceed `review_budget_changed_lines: 400`. Chained PRs are **mandatory**, not optional — single-PR would hide the storage/migration shape behind service+UI churn and would make reviewers less able to localize a fault.

### Slice 1 — Backend storage + service + repo + permission seed (PR #1 → `feature/cmdb-ai-handoff-s1`)

**Goal:** the proposal graph layer is live and persisted; HTTP surface is not yet wired.

- Files: `backend/migrations/005_ci_proposal_schema.cypher` (new), `backend/repositories/cmdb_proposal_repo.py` (new), `backend/services/cmdb_proposal_service.py` (new), `backend/services/audit_service.py` (modify — extend `AUDIT_CONTEXT_ALLOWED_KEYS` + add `redact_manifest_secrets`), `backend/models/user.py` (modify — add 2 enum members), `backend/models/core.py` (modify — add `ManifestPayload` Pydantic), `backend/seed_roles.py` (modify — extend `SYSTEM_ROLE_PERMISSION_UPGRADES` + role definitions).
- Tests: `backend/tests/test_cmdb_proposal_repo.py`, `backend/tests/test_cmdb_proposal_service.py`, `backend/tests/test_audit_redaction.py`, extend `backend/tests/test_ai_permissions.py` and `backend/tests/test_audit_service.py`.
- Estimated changed lines: **~340** (under 400).

### Slice 2 — Backend MCP server + HTTP endpoints + guard integration (PR #2 → `feature/cmdb-ai-handoff-s2`, targets `feature/cmdb-ai-handoff-s1`)

**Goal:** external clients can propose/list/approve/revoke; AI guard blocks bulk.

- Files: `backend/routers/cmdb_proposals.py` (new), `backend/mcp/cmdb_proposal_server.py` (new), `backend/services/ai_guard_service.py` (modify — add `propose_ci` cooldown + bulk threshold), `backend/main.py` (modify — `app.include_router` + flag gate).
- Tests: `backend/tests/test_cmdb_proposal_router.py`, `backend/tests/test_mcp_cmdb_proposal_server.py`, extend `backend/tests/test_ai_guard_service.py` and `backend/tests/test_routers_nodes.py` (regression — assert `POST /api/nodes` unchanged).
- Estimated changed lines: **~280** (under 400).

### Slice 3 — Frontend list/detail/diff + AIAgentConsole badge (PR #3 → `feature/cmdb-ai-handoff-s3`, targets `feature/cmdb-ai-handoff-s2`)

**Goal:** operators can review and approve from the UI.

- Files: `frontend/components/cmdb/proposals/{ProposalList,ProposalDetail,ProposalDiffView,ProposalActions,ProposalAuditTimeline,ProposalBadge}.tsx` (6 new), `frontend/pages/ProposalsCmdbPage.tsx` (new), `frontend/hooks/queries/{useProposalsQuery,useApproveProposal,useRevokeProposal,useProposalCountQuery}.ts` (4 new), `frontend/services/{cmdbProposals,queryKeys,queryResources}.ts` (modify), `frontend/App.tsx` (modify — add 2 routes), `frontend/components/AIAgentConsole.tsx` (modify — add badge).
- Tests: `frontend/components/cmdb/proposals/__tests__/*.test.tsx` + Playwright `frontend/e2e/cmdb-proposals.spec.ts`.
- Estimated changed lines: **~380** (under 400).

> **Doc updates** (`docs/CMDB_AI_MANIFEST.md`, `docs/AI_AGENT_GUIDE.md`) can ride in Slice 1 (lowest risk) — they don't ship runtime code and reviewers benefit from seeing the agent-facing contract alongside the storage shape.