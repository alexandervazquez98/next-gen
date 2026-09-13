# Exploration: feat-cmdb-ai-handoff

**Change**: `feat-cmdb-ai-handoff`
**Phase**: sdd-explore (evidence mapping; NO solution proposed)
**Artifact store**: openspec (path: `openspec/changes/feat-cmdb-ai-handoff/explore.md`)

---

## Goal

Future SDD change will deliver an **AI-agent HITL (Human-In-The-Loop) flow for creating CIs (Configuration Items) in the CMDB**: an AI agent proposes CIs via structured manifests; a human approves before commit.

This document maps the *current* state of the repo so that the proposal, spec, design, and tasks phases can scope against real, sourced code. **Nothing here is a proposal.**

---

## 1. CI creation path today (Backend)

### 1.1 Endpoint

- **`POST /api/nodes`** — `backend/routers/nodes.py:94-172` (annotated `@router.post("")` on `router = APIRouter(prefix="/nodes", tags=["Nodes"], ...)` at `backend/routers/nodes.py:15-19`).
- Docstring is explicit: *"`Create or Update a Configuration Item (CI). Enforces CI_EDIT permission.`"* (`backend/routers/nodes.py:101-104`).
- Note: the same endpoint is currently an **upsert** (no separate create-only endpoint). The docstring, the repo method name, and the audit event_type all reinforce this dual semantics:

  ```python
  # backend/routers/nodes.py:94-172
  @router.post("")
  async def create_node(
      request: Request,
      node_payload: dict[str, Any] = NODE_PAYLOAD_BODY,
      current_user: User = CURRENT_USER_DEP,
      db: Session = PG_DB_DEP,
  ):
      """Create or Update a Configuration Item (CI)."""
  ```

### 1.2 Validation

- `Node.model_validate(node_payload)` runs first (`backend/routers/nodes.py:118`). ValidationError special-cases `public_ip` to return HTTP 400, otherwise 422 (`backend/routers/nodes.py:119-133`).
- Service then re-validates defensively at `backend/services/node_service.py:164-170` — if a caller bypasses Pydantic, it still gets HTTP 400.
- Permission gate: `check_permission(UserPermission.CI_EDIT, current_user)` is called both in router (`backend/routers/nodes.py:106`) and service (`backend/services/node_service.py:156-157`).

### 1.3 Audit hooks

- Pre-commit denials → `audit_service.record_denied()` with `target_type="ci"`, `source="nodes"` (`backend/routers/nodes.py:43-55`).
- Validation/service errors → `audit_service.record_critical_change(... event_type=CI_CREATE_OR_UPDATE, outcome=VALIDATION_FAILURE, ...)` (`backend/routers/nodes.py:121-131`, `backend/routers/nodes.py:148-158`).
- Success path → outcome=`SUCCESS`, reason=`"ci_saved"` (`backend/routers/nodes.py:161-171`).
- A parallel endpoint `DELETE /api/nodes/{node_id}` (`backend/routers/nodes.py:175-234`) emits `CI_DELETE` audit events.

### 1.4 No draft / preview / proposed state

- The single `topology_repo.upsert_node(node)` call (`backend/services/node_service.py:172`) performs an immediate `MERGE (n:CI {id: $id}) SET n.name = $label ...` and then re-runs metric reconciliation (`backend/services/node_service.py:175-186`).
- There is no `status='DRAFT'` / `status='PROPOSED'` / `proposed_by` / `approved_by` field on the `Node` model (`backend/models/core.py:10-46`), no equivalent field on `:CI` properties in repository code (`backend/repositories/topology_repo.py:62-101`), and no matching audit event_type today.
- Conclusion: the system has **no CI draft state today**. A HITL flow will need to add one (most likely as a new label/property on `:CI` or a parallel `:CIPendingProposal` graph model).

---

## 2. CI classes catalog (where do "Router", "Server", "Application" come from?)

### 2.1 No static class catalog file

- I searched for `ci_classes.*`, `class_catalog.*`, `ci_class.*`, hard-coded enums of types, JSON/YAML of allowed types. **None exists.**
- The `Node.type` field on the Pydantic schema is **free-form `str`** with no Literal/Enum constraint (`backend/models/core.py:10-46`):
  ```python
  # backend/models/core.py:10-46
  class Node(BaseModel):
      """Pydantic model representing a Configuration Item (CI) Node."""
      id: str
      label: str
      type: str
      ...
  ```

### 2.2 Categories are live Neo4j nodes

- The category list is stored as a dynamic catalog in Neo4j: each CI node is linked via `(:CI)-[:CATEGORIZED_AS]->(:Category {name: $type})` (set in `backend/repositories/topology_repo.py:77` and `:153`).
- `Category {name, icon_key?}` is managed through `/api/categories` (CRUD operations defined at `backend/routers/catalog.py:23-73`):

  ```python
  # backend/routers/catalog.py:18-26
  class CategoryUpdate(BaseModel):
      name: Optional[str] = None
      icon_key: Optional[str] = None

  @router.get("/categories", ...)
  async def get_categories(...):
      return catalog_service.get_categories()
  ```

- Frontend `CIEditor.tsx:26-40` fetches the category list from `/api/categories` on mount and renders them as `<option>` elements in the "Network Layer" dropdown (`frontend/components/CIEditor.tsx:213-222`), defaulting to literal `"INFRASTRUCTURE (Default)"`.
- Excel bulk upload validates against the current set of Category names from Neo4j (`backend/services/node_service.py:239-275`):
  ```python
  # backend/services/node_node_service.py:262-275 (typo as observed)
  ntype = str(row.get("NetworkLayer", "INFRASTRUCTURE")).strip()
  ...
  if ntype != "INFRASTRUCTURE" and ntype not in valid_layers:
      validation_errors.append(...)
  ```

### 2.3 No DB-level uniqueness / constraint on Category

- `backend/migrations/` contains 4 cypher files (`001_rtu_sensor_schema.cypher`, `002_generic_device_schema.cypher`, `003_mqtt_monitoring_mapping.cypher`, `004_mqtt_metric_result_idempotency.cypher`) plus `itsm_service_catalog.cypher`. **None defines `CREATE CONSTRAINT ... FOR (:Category)` or `(:CI)`.** Constraints that DO exist: `rtu_id_unique`, `device_id_unique`, `metric_id_unique`, `service_catalog_service_id`, `value_stream_dictionary_value`, plus some indexes.

### 2.4 Sample class strings seen in tests

- Tests reference `"Router"`, `"Routers"`, `"Core Router"` as `category` values (e.g. `backend/tests/test_routers_catalog.py:186`, `backend/tests/test_topology_repo_nodes.py:96`, `backend/tests/test_event_service_smoke.py:251`). These are example values seeded from data, **not a closed enum**.
- Excel template at `backend/services/node_service.py:393-414` shows defaults like `INFRASTRUCTURE`, `Cisco` brand, `ASR-1000` model — also illustrative, not exhaustive.

### 2.5 Implication for HITL flow

- Any future manifest must use the **current Category name as the value** of `Node.type` (or `category`). At human-review time the UI must show the live list from `/api/categories`, not a static enums list. This is a constraint, not a feature gap.

---

## 3. CI attribute schema per class

### 3.1 One shared schema: `Node` (`backend/models/core.py:10-46`)

- There is **one** Pydantic model for ALL CI "classes". No per-class typed models (no `RouterNode(BaseModel)`, no `ServerNode(BaseModel)`):

  ```python
  # backend/models/core.py:10-46
  class Node(BaseModel):
      """Pydantic model representing a Configuration Item (CI) Node."""
      id: str                                       # required
      label: str                                    # required
      type: str                                     # required (free-form; see §2)
      status: str | None = "OK"                     # default OK
      ip: str | None = None
      public_ip: str | None = None                  # v4 or v6; validator at :37-46
      location: dict | None = None                  # {lat, long}
      metadata: dict | None = {}
      owner: str | None = None
      location_name: str | None = None
      pollingInterval: int | None = 60
      snmp: dict | str | None = None                # dict OR JSON string
      brand: str | None = None
      model: str | None = None
      serialNumber: str | None = None
      firmwareVersion: str | None = None
      metrics: list[dict[str, Any]] | None = []
      @field_validator("public_ip")
      @classmethod
      def _validate_public_ip(cls, value):
          ...
  ```

- Required fields: `id`, `label`, `type`.
- Optional / defaulted: everything else (with `status` defaulting to `"OK"`, `pollingInterval` to `60`).
- Per-class attribute schemas do not exist. A "Router" and a "Server" share the same flat `Node` shape.
- Hardware model binding happens via `Category` lookup; the CI's `brand` and `model` strings are then matched against the `(:HardwareModel {brand, model})` graph to wire `(:CI)-[:IS_MODEL]->(h)` (`backend/repositories/topology_repo.py:80-81`).

### 3.2 `NodeMetadataUpdate` AI-safe subset

- `backend/services/node_service.py:25-50` defines a smaller schema for AI agents:
  ```python
  ALLOWED_AI_METADATA_FIELDS = {"status", "pollingInterval", "owner", "location_name", "metadata"}
  BLOCKED_AI_UPDATE_FIELDS = {"id", "label", "type", "brand", "model", "serialNumber",
                              "firmwareVersion", "ip", "snmp", "location"}
  ```
- `validate_ai_metadata_update` (`backend/services/node_service.py:53-61`) returns `(False, blocked_fields)` if a write touches any BLOCKED field. This is the *only* AI-specific field-allowlist; it predates this change.

### 3.3 Uniqueness checks at create-time

- `topology_repo.upsert_node` (`backend/repositories/topology_repo.py:62-101`) uses `MERGE (n:CI {id: $id})`. Conflict semantics: **same id ⇒ silent update**, not error. No duplicate-by-IP, no duplicate-by-label check exists.
- No uniqueness validation in `node_service.create_update_node` (`backend/services/node_service.py:150-188`).

---

## 4. Validation pipeline (what runs today when a CI is created)

| Layer | Mechanism | Source |
|-------|-----------|--------|
| 1. Authentication | `get_current_active_user` JWT/cookie dep | `backend/routers/nodes.py:21` |
| 2. Permission gate | `check_permission(CI_EDIT, user)` → HTTP 403 if missing | `backend/routers/nodes.py:106`; replayed in service at `backend/services/node_service.py:156-157` |
| 3. Pydantic validation | `Node.model_validate(node_payload)` → 422 (or 400 for public_ip) | `backend/routers/nodes.py:118-133` |
| 4. Service re-validation | `Node.model_validate(node.model_dump())` → 400 | `backend/services/node_service.py:164-170` |
| 5. Repository `MERGE` | `topology_repo.upsert_node(node)` (`MERGE (:CI {id:$id})`) | `backend/repositories/topology_repo.py:62-101` |
| 6. Default PING metric | `topology_repo.create_default_ping_metric(node.id, node.label)` when `node.ip` is set | `backend/services/node_service.py:175-176` |
| 7. Metric reconciliation | `reconcile_node_metrics(node_dict)` add/remove metric bindings based on hardware | `backend/services/node_service.py:179-186` |
| 8. Audit record | `audit_service.record_critical_change(...CI_CREATE_OR_UPDATE, SUCCESS, "ci_saved", ...)` | `backend/routers/nodes.py:161-171` |

- **No business-rule validators** beyond Pydantic types; no duplicate-IP guard; no duplicate-label guard; no SLA / category-must-exist gate at write-time (only Excel upload validates against Category, and that via `topology_repo.get_valid_owners_and_layers()` rather than at the API layer).
- **Atomicity**: there is no explicit transaction wrapper. The MERGE write and the metric reconciliation are separate calls; an interruption between them yields partially-applied state.

---

## 5. Graph model (Neo4j)

### 5.1 CI node

- Label: `:CI` with the property `id` used as the merge key.
- Properties written by `upsert_node` (`backend/repositories/topology_repo.py:62-101`):
  - Required: `id`, `name` (from `Node.label`).
  - Optional: `layer` (from `Node.type`), `status`, `ip`, `owner`, `location_name`, `brand`, `model`, `serialNumber`, `firmwareVersion`, `snmp` (JSON string), `pollingInterval`, `public_ip`, `location` (Neo4j `point({latitude, longitude})`), `updated_at = datetime()`.
- **No `:CI` uniqueness constraint is in the migrations** (only `:Device`, `:Metric`, `:RTU`, `:ServiceCatalog`, `:MetricDictionary` get `CREATE CONSTRAINT ... IF NOT EXISTS`). `id` uniqueness is enforced *only* via the MERGE key in the service code, not at the database level.

### 5.2 Relationship patterns written

- `(:CI)-[:CATEGORIZED_AS]->(:Category {name, icon_key?})` (`backend/repositories/topology_repo.py:77`, `:153`).
- `(:CI)-[:OWNED_BY]->(:OwnerGroup {name})` when `node.owner` set (`backend/repositories/topology_repo.py:78-79`, `:154`).
- `(:CI)-[:IS_MODEL]->(:HardwareModel {brand, model})` when both `brand` and `model` set (`backend/repositories/topology_repo.py:80-81`).
- `(:CI)-[:HAS_METRIC]->(:MetricDef)` and `(:MetricDef)-[:HAS_METRIC {status, last_value, last_updated}]->(:CI)` are added by `reconcile_node_metrics` (called from `node_service.create_update_node` at `:179`).
- Other relationship types (HOSTED_IN, CONNECTS_TO, etc.) live in `backend/services/relationship_types.py` (re-exported via `topology_repo.py:24-28`) and are enforced by the `_VALID_NODE_LABELS` frozenset (`backend/repositories/topology_repo.py:185-194`) plus `validate_ci_relationship_type` for injection prevention.

### 5.3 Cascade behavior

- `delete_node` uses `DETACH DELETE` (`backend/repositories/topology_repo.py:104-107`), removing all incident relationships.

---

## 6. Frontend creation UX

### 6.1 Mount surface

- `AdminPage.tsx` lazy-loads `CIEditor` (`frontend/components/AdminPage.tsx:5`, `:224`). Routes are configured in `frontend/App.tsx:231-233` (route `/` → `SystemDashboard`) and `:229-246` (route `/monitoring` → `MonitoringConsole`). Edit CI flows live on `/admin` or per-page admin panels.
- `frontend/components/CIEditor.tsx` is the single component for create AND update (`frontend/components/CIEditor.tsx:6-79`). It is a side panel (`w-[450px]`).
- `CIEditor.prefill.test.tsx` (`frontend/components/__tests__/CIEditor.prefill.test.tsx`) mocks `/api/categories`, `/api/owners`, `/api/hardware` and tests mount/unmount behavior.

### 6.2 Form fields

- ID auto-generated as `CI-${randomBase36(5)}` (`frontend/components/CIEditor.tsx:43, 63, 76`). Operator cannot edit it.
- Common Name (`label`), Brand (select-or-input), Model (select-or-input), Serial Number, Firmware Version, IP Address, Owner Group (from `/owners`), Network Layer (from `/categories`), Op Status (`ACTIVE|EXCEPTION|MAINTENANCE`), Location Name, lat/long. Lines 96-270.
- SNMP Agent Config block: Version v2c/v3, port, readCommunity/writeCommunity OR authKey, pollingInterval (min 10). Lines 274-346.
- **No "preview"/"draft"/"proposed" state.** The only actions are `node ? "UPDATE CONFIG" : "COMMIT TO CMDB"` (line 363). Submitting immediately calls `onSave` → POST `/api/nodes`.

### 6.3 Submit behavior

- `handleSubmit` (`frontend/components/CIEditor.tsx:69-79`):
  ```typescript
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onSave(formData as GraphNode);
    if (!node) {
      setFormData({ ...defaultState, id: `CI-${Math.random()...}` });
    }
  };
  ```
- No multi-step / diff preview. No "save as draft". No JSON validation pre-flight beyond the field types.

---

## 7. AI agent surface area in the repo today

### 7.1 Authentication & roles

- AI roles are JWT subjects whose `role` starts with `AI_` (`backend/services/auth_service.py` is the dep; the convention is checked in the router at `backend/routers/nodes.py:262`).
- `AIPermission` enum at `backend/models/user.py:16-26`:
  ```python
  AI_RUN_DIAGNOSTIC = "AI_RUN_DIAGNOSTIC"
  AI_VIEW_ALL = "AI_VIEW_ALL"
  AI_EVENT_ACK = "AI_EVENT_ACK"
  AI_EVENT_COMMENT = "AI_EVENT_COMMENT"
  AI_CI_UPDATE_METADATA = "AI_CI_UPDATE_METADATA"
  AI_EVENT_CLOSE = "AI_EVENT_CLOSE"
  AI_DICTIONARY_PREVIEW = "AI_DICTIONARY_PREVIEW"
  ```
- `/api/permissions/` returns BOTH enums (`backend/routers/permissions.py:14-18`) so clients can introspect the full surface.
- `backend/seed_roles.py:57-81` seeds two system roles: `AI_DIAGNOSTIC` (read+ack+comment+CI-metadata only) and `AI_OPERATOR` (everything PLUS `AI_EVENT_CLOSE`).

### 7.2 LLM integration

- Single backend entry: `POST /api/ai/chat` (`backend/routers/ai.py:308-619`) hitting LM Studio (`config.get_lm_studio_settings()`). No OpenAI, no Anthropic, no Claude, no native tool/function-calling loop is wired.
- Backend-owned harness pattern: `maybe_run_harness(intent, neo4j_driver, user)` in `backend/services/ai_chat_service.py:608` dispatches to fixed intents: `event_list`, `active_events`, `availability_check`, `availability_check_batch`. There is no `create_ci` / `provision` intent today.
- Frontend `chatWithAIAgent()` (`frontend/services/geminiService.ts:80-99`) only POSTs to `/ai/chat` with `{query, context, intent?}`. The frontend also references `@google/genai` SDK for an `analyzeIncident()` helper (`frontend/services/geminiService.ts:1-67`) — this is **unused dead code on the Gemini side**: nothing imports `analyzeIncident` in production code paths; the call surface is exclusively `/api/ai/chat`. The `@google/genai` SDK stays as a non-default fallback candidate.

### 7.3 Existing tool/function definitions

- **None.** There is no OpenAI-style `tools=[{name, parameters, ...}]` schema wired to `/api/ai/chat`. All agent-side effects are routed through explicit `AIPermission` gates + `ai_guard_service` and through per-intent backend handlers.
- The AI Agent Guide (`docs/AI_AGENT_GUIDE.md:37-55`) documents that AI agents **cannot create CIs** today:
  > *"Update CI metadata | `PUT /api/nodes/{node_id}/metadata` | Only these fields allowed: {status, pollingInterval, owner, location_name, metadata}"*
- This is the *only* write endpoint AI agents may exercise on CIs, and a 403 is returned for everything else (`backend/routers/nodes.py:296-299`).

### 7.4 Guardrail plane (prerequisite for HITL)

- `backend/services/ai_guard_service.py` exposes:
  - `check_cooldown` (in-memory TTL; `COOLDOWNS` dict at `:28-33` includes `ci_metadata_update: 120s`).
  - `check_behavioral_guards` (close-without-diagnostic, ack flood, metadata stampede — `:187-300`).
  - `check_bulk_detection` (>10 entities, >50 ops/hour, >30 distinct CIs/hour → `escalation_required=True`; `:303-375`).
  - `check_all_guards(...)` aggregates all three (`:378-416`).
- Operational log: `AIOperationLog` (`backend/models/ai_operation_log.py:6-29`) persists `ai_persona, ai_agent_id, operation, target_type, target_id, target_name, result, blocked_reason, request_context, ...` for every guarded action.

### 7.5 Chat harness denial semantics

- Spec at `openspec/specs/ai-chat-harness-guardrails/spec.md:1-100` establishes two-layer semantics:
  - HTTP **403** when permission/role is missing.
  - HTTP **200** with `harness_result.denied=true` and a stable `reason_code` when `ai_guard_service` blocks the call but permission is otherwise valid.
- `record_operation(ai_agent_id, ..., result="blocked"|"escalated"|"success")` writes the outcome to `ai_operation_log`.

### 7.6 Frontend AI surface

- `AIAgentConsole.tsx` (`frontend/components/AIAgentConsole.tsx:1-144`) is a basic chat UI that sends the user message to `chatWithAIAgent` and renders the reply text. **No structured rendering** of proposed CI manifests, no diff/approve UI.

---

## 8. Audit & mutation logging

### 8.1 AuditEvent table

- `backend/models/audit_event.py:14-46`:
  - Table: `audit_events`.
  - Fields: `schema_version, event_type, outcome, actor_username, actor_role, target_type, target_id, target_label, source, ip_address, user_agent, reason, context (JSON), created_at`.
  - Indexes: `(created_at, event_type)`, `(created_at, outcome)`, `(created_at, actor_username)`, `(target_type, target_id, created_at)`.
- Helpers in `backend/services/audit_service.py`:
  - `record_auth_event` (`:181-209`)
  - `record_critical_change` (`:212-245`) — this is what CI mutations call.
  - `record_denied` (`:248-264`) wraps `record_critical_change` with `event_type='ACCESS_DENIED'`, `outcome='DENIED'`.

### 8.2 CI mutation events emitted today

- `event_type=CI_CREATE_OR_UPDATE` with `target_type="ci"`, `source="nodes"`. Three outcomes per attempt: `VALIDATION_FAILURE` (Pydantic or service error), `SUCCESS` ("ci_saved"), or `ACCESS_DENIED` (via `record_denied` with reason `"missing_permission"` or `"service_denied"`).
- `event_type=CI_DELETE` for `DELETE /api/nodes/{node_id}`.
- `event_type=CI_UPDATE_METADATA` for `PUT /api/nodes/{node_id}/metadata`.

### 8.3 Distinguishing AI vs human

- `actor_role` is set from the actor's role claim (`_actor_role` in `audit_service`). AI agents appear with `actor_role="AI_DIAGNOSTIC"` or `"AI_OPERATOR"`; humans with `"ADMIN"`, `"OPERATOR"`, etc. This is the discriminator available today.

---

## 9. HITL / approval precedents in the repo

### 9.1 Per-event escalation (most relevant)

- `backend/services/escalation_notifier.py:53-171` publishes a CRITICAL event closure attempt by an AI to MQTT topic `alerts/human/escalation` with a **30-minute timeout**.
- Escalation payload (`:28-50`) carries `escalation_id, ai_persona, ai_agent_id, event_id, event_message, ci_id, ci_name, timeout_at, created_at, topic`.
- In-memory cache `_active_escalations: dict[escalation_id, dict]` (`:21`, `:174-198`) is cleared on timeout or via `clear_escalation(escalation_id)` after approval.
- Hook site: `backend/routers/events.py:257` — *"blocked_reason='CRITICAL event requires human approval to close'"*.

### 9.2 Mapping approval flow (DRAFT/APPROVED/REVOKED)

- `backend/repositories/mqtt_mapping_repo.py` already encodes a *PROPOSE → APPROVE* lifecycle:
  - `create_draft(...)` writes `(:MqttMetricMapping {status: 'DRAFT'})` (`:172-270`).
  - `approve(mapping_id, approved_by)` flips to `APPROVED`, with `approved_by`, `approved_at`, optimistic version bump (`:386-507`).
  - Status constants: `MAPPING_STATUS_DRAFT`, `MAPPING_STATUS_APPROVED`, `MAPPING_STATUS_REVOKED`.
- This is the **only** model in the repo with a multi-status lifecycle tied to operator approval. It is, in form, the most direct precedent any CI-proposal HITL flow could mirror.

### 9.3 AI guard escalation flag

- `GuardResult.escalation_required` field (`backend/models/ai_guard_models.py:10-...`) is set True by `check_bulk_detection` (`backend/services/ai_guard_service.py:312`); it's a soft "needs approval" hint, not a separate persistence record beyond the operation log.

### 9.4 No generic "proposals" / "pending changes" table

- I searched for `proposal`, `pending_change`, `draft_change`, `change_request`, `approval`. The only matches in business code (excluding docs) are the mqtt-mapping flow and the escalation notifier. There is **no** generic document-style "pending change" or "request for change" table that a CI proposal could plug into.

---

## 10. Existing tests for CI creation

### 10.1 pytest coverage

- `backend/tests/test_routers_nodes.py` — 100+ lines of POST/DELETE tests at `:391-727`:
  - `test_create_node_unauthenticated` (`:398`),
  - `test_create_node_no_ci_edit_permission` (`:410`),
  - `test_create_node_admin_success` (`:438`),
  - `test_create_node_operator_with_ci_edit` (`:480`),
  - `test_create_node_invalid_payload` (`:512`),
  - `test_create_node_invalid_public_ip_returns_400_and_audits` (`:531`).
- `test_metadata_update_unauthenticated` and AI-metadata tests at `:877` and `:1041`. The test uses `@patch("routers.nodes.validate_ai_metadata_update", return_value=(False, ["brand"]))` to verify AI is denied for blocked fields.
- `backend/tests/test_routers_catalog.py` — covers category CRUD, including `Router`/`Edge Router` rename and usage count. (`:186, 255, 271, 286, 313, 358, 476`.)
- `backend/tests/test_node_service.py:370` — tests with category="Core Router".
- `backend/tests/test_topology_repo_nodes.py:96` — asserts `category="Router"` round-trips through the repo.
- `backend/tests/test_event_service_smoke.py` and `test_routers_metrics_events.py` — fixtures with `"category": "Routers"`.

### 10.2 Vitest (frontend)

- `frontend/components/CIEditor.prefill.test.tsx` (`frontend/components/__tests__/CIEditor.prefill.test.tsx`) — covers prefilling, brand/model cascading, and submit-with-empty-ID.
- No test exercises a "draft → review → approve" flow because **no such UX exists**.

### 10.3 Fixtures and convention

- Tests use `MagicMock()` patched Neo4j driver (`_mock_neo4j_driver = MagicMock(); with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver): from main import app` at `test_routers_nodes.py:31-36`) to avoid live database calls. Topology repo methods are mocked at the `routers.nodes.node_service.*` boundary.
- AI guard tests follow the same pattern (`backend/tests/test_ai_guard_service.py`, `test_ai_chat_service.py`).

---

## 11. Findings (synthesized)

1. **The CI creation path today is a single atomic MERGE with no review state.** Any HITL flow must add a new persistent state (e.g., `:CIProposed {id, payload_json, status, proposed_by, reviewed_by?, ...}`) because the existing `Node` model lacks any draft/proposed fields and `topology_repo.upsert_node` performs an immediate `MERGE`.
2. **The "CI class" (Node.type) is not a closed enum — it is a live Category in Neo4j.** Class list comes from `GET /api/categories`, mutated via `POST /api/categories`. No DB-level uniqueness constraint on `:Category.name`. An AI manifest must resolve the class at run time from this live list; trying to encode a static list risks drift.
3. **No per-class attribute schemas exist.** All CIs (Router/Server/Application) share one `Node` Pydantic schema in `backend/models/core.py:10-46`. The only hard constraint today is the `public_ip` regex via `ipaddress.ip_address`. There is no duplicate-IP check, no duplicate-label check, no category-must-exist gate at HTTP write time.
4. **There IS precedent for a draft→approved lifecycle on a different model.** `mqtt_mapping_repo.create_draft(...)/approve(...)` is the cleanest in-repo template for proposal persistence; reuse-shaped, not literally reusable.
5. **There IS precedent for "AI raises request for human action" via the escalation notifier.** `services/escalation_notifier.py` publishes to MQTT `alerts/human/escalation` with a 30-min TTL; for CI creation there is no such channel yet.
6. **There is NO precedent for a generic pending-change / proposal table.** The audit_event table records *what happened*, not *what is awaiting approval*. A new table or Neo4j node label is required.
7. **Audit is already dense and rich.** The `audit_events` schema (`backend/models/audit_event.py`) can carry `event_type`, `actor_role`, `outcome=SUCCESS|VALIDATION_FAILURE|DENIED`, and a JSON `context` payload. AI vs human is encoded as `actor_role=AI_DIAGNOSTIC|AI_OPERATOR` versus `ADMIN|OPERATOR|VIEWER`.
8. **AI permissions today forbid creating CIs.** The frontend Gemini SDK and `analyzeIncident` are dead-code paths; the live AI surface is exclusively `/api/ai/chat`. There is no `create_ci` tool function bound to LM Studio. The AI Agent Guide (`docs/AI_AGENT_GUIDE.md:37-55`) explicitly documents "no CI create".
9. **The two-layer gate (permission then guardrail) is the established contract** (per `openspec/specs/ai-chat-harness-guardrails/spec.md`). A future proposal should reuse this split: `CI_EDIT` permission = the user is *allowed* to call the new propose endpoint; AI guardrail = the AI agent's *behavioral* eligibility.

---

## 12. Open Questions (must be resolved in sdd-propose or sdd-spec — not now)

1. **Where should a proposed CI live?** Options: (a) a Neo4j label like `:CIProposed` separate from `:CI`; (b) a `status` enum on `:CI` (e.g., `DRAFT`, `APPROVED`, `REVOKED`) mirroring `MqttMetricMapping`; (c) a Postgres table; (d) a JSON payload stored elsewhere (audit_event `context`?). The current explore does not pick.
2. **What is the human review surface?** No UI exists yet. The escalation pattern publishes to MQTT but doesn't define what consumes it. The `MultiSelectCIs.tsx` / `VisualRelationshipEditor.tsx` style pattern in `frontend/components/` suggests a side panel; nothing on review/approval yet.
3. **What is the manifest schema an AI agent must use?** It could be (a) the existing `Node` shape, (b) a narrower AI-safe subset (like `NodeMetadataUpdate` but extended), or (c) a new "Manifest" Pydantic model. The proposal phase must pick.
4. **How should existing AI guards (cooldown, behavioral, bulk) extend to "propose CI"?** `COOLDOWNS` (`backend/services/ai_guard_service.py:28-33`) currently lists `diagnose, ack, close, ci_metadata_update`. A new "propose_ci" cooldown key is one option; a richer per-CI-class rule is another.
5. **What is the relationship between a CI proposal and the existing Excel bulk import?** `bulk_upload_nodes` (`backend/services/node_service.py:232-375`) bypasses any per-CI review. Should the new HITL flow also be triggered by upload, or only by the AI agent surface?
6. **Who approves?** Today `check_permission(CI_EDIT, user)` is the only gate. The docs/AI_AGENT_GUIDE.md says AI CANNOT have CI_EDIT (no AI permission enum member grants it). If approvers need a *new* permission (e.g., `CI_APPROVE_PROPOSAL`) that does not yet exist in `UserPermission` or `AIPermission` enums (`backend/models/user.py:16-58`), must it be added?
7. **Time-out and expiration.** The escalation pattern uses 30 minutes as a TTL; should a CI proposal carry the same? Should expired proposals auto-revoke, or stay pending?
8. **Frontend review UX placement.** Routes are `/`, `/monitoring`, and the admin pages host the editor; should the review queue live in `AIAgentConsole` (`frontend/components/AIAgentConsole.tsx`) or open as a separate panel/route?
9. **Authoring guidelines for the AI.** The deliverable doc will guide the AI on how to propose. Should it live at `docs/AI_AGENT_GUIDE.md` (extending `## CIs`) or in a new file like `docs/CMDB_AI_MANIFEST.md`?

---

## 13. Affected Areas (file paths only — for the sdd-propose phase to scope)

Backend (Python):
- `backend/routers/nodes.py` — POST handler is the place to wire permission + AI-guard + new state
- `backend/services/node_service.py` — service-level `create_update_node` is the executor; ALLOWED_AI_METADATA_FIELDS lives here
- `backend/repositories/topology_repo.py` — graph writer; `_VALID_NODE_LABELS` and `upsert_node` are the MERGE sites
- `backend/models/core.py` — `Node` Pydantic model (line 10-46); `Link`, `Category`, etc.
- `backend/models/user.py` — `AIPermission` (16-26) and `UserPermission` (28-58) enums
- `backend/models/audit_event.py` — persistent audit shape (likely no change)
- `backend/services/audit_service.py` — recording helpers (likely reuse)
- `backend/services/ai_guard_service.py` — guardrail plane (likely extend)
- `backend/services/ai_chat_service.py` — chat harness dispatch (likely extend only if AI must propose via chat)
- `backend/services/escalation_notifier.py` — escalation TTL/publish precedent
- `backend/routers/ai.py` — chat entry (if a new intent is added)
- `backend/seed_roles.py` — role bootstrap (if a new permission is added)

Migrations:
- `backend/migrations/*.cypher` — possibly add `:CIProposed` or `:CI.status` DDL

Frontend (TS/React):
- `frontend/components/CIEditor.tsx` — current create/update UX (may need a "Propose as new CI" branch)
- `frontend/components/AdminPage.tsx` — hosts `CIEditor` lazy load
- `frontend/components/AIAgentConsole.tsx` — chat UI (if HITL ACK flows through it)
- `frontend/components/MultiSelectCIs.tsx`, `VisualRelationshipEditor.tsx` — adjacent topology UIs (only relevant if review queue piggybacks on existing surfaces)
- `frontend/services/api.ts` — central API wrapper; new endpoint wrapper
- `frontend/services/queryResources.ts` — type definitions for CI fetch
- `frontend/services/geminiService.ts` — currently the only AI client wrapper; `chatWithAIAgent` is the bridge

Docs:
- `docs/AI_AGENT_GUIDE.md` — agent-facing capabilities table; will need updating (line 37-55)
- `docs/domain/...` — possibly a new `cmdb-ai-manifest.md`

Specs / existing OpenSpec context:
- `openspec/specs/cmdb-graph-level-of-detail/spec.md` — adjacent (topology read concerns only)
- `openspec/specs/cmdb-orphan-detection/spec.md` — adjacent
- `openspec/specs/audit-logging/spec.md` — adjacent (audit shape already supports new event types)
- `openspec/specs/ai-chat-harness-guardrails/spec.md` — defines the two-layer pattern any new AI-driven endpoint should follow

Tests:
- `backend/tests/test_routers_nodes.py` — add new tests
- `backend/tests/test_ai_guard_service.py`, `backend/tests/test_ai_chat_service.py` — extend if new AI guard key
- `frontend/components/CIEditor.prefill.test.tsx` — extend if editor grows a "Propose" branch
- New tests for any new router / service component added in apply

---

## 14. Ready for Proposal

- **Ready for `sdd-propose`**: Yes. The evidence above is sufficient to draft a Problem Statement, Scope, and Approach. Proposal phase should NOT design yet — only propose *what* should change (a HITL flow for AI-proposed CI creation) and *why*, with reference to the parts of §11 that motivate each decision.
- **Open questions to raise at proposal time** (in priority order): §12.1 (storage shape), §12.6 (new permission?), §12.3 (manifest schema), §12.4 (guard key), §12.7 (TTL).
- **Critical guardrails before proposal is finalized**:
  - The repo already enforces `sdd.strict_tdd.test_first_required=true` (`openspec/config.yaml:14-19`). Any new endpoint/service MUST ship tests in the same change. Plan a TDD sequence in tasks.
  - `review_budget_changed_lines: 400` (`openspec/config.yaml:10`). Backend-only changes plus tests will likely exceed this; stage the work into chained PRs.
  - `delivery_strategy=ask-on-risk` from preflight ⇒ during `sdd-tasks` expect an explicit ask before applying oversized slices.

---

## 15. References (line-numbered, all observed this session)

- `backend/routers/nodes.py:15-19` — router prefix
- `backend/routers/nodes.py:43-55, 58-81` — `_record_ci_denied`, `_record_ci_change` helpers
- `backend/routers/nodes.py:94-172` — `POST /api/nodes` upsert
- `backend/routers/nodes.py:175-234` — `DELETE /api/nodes/{node_id}`
- `backend/routers/nodes.py:245-361` — `PUT /api/nodes/{node_id}/metadata` (AI-safe subset)
- `backend/services/node_service.py:25-50` — `ALLOWED_AI_METADATA_FIELDS`, `BLOCKED_AI_UPDATE_FIELDS`, `NodeMetadataUpdate`
- `backend/services/node_service.py:53-61` — `validate_ai_metadata_update`
- `backend/services/node_service.py:64-147` — `get_nodes` (read path)
- `backend/services/node_service.py:150-188` — `create_update_node`
- `backend/services/node_service.py:232-375` — `bulk_upload_nodes` (Excel path)
- `backend/services/node_service.py:393-431` — `get_node_template` (Excel)
- `backend/repositories/topology_repo.py:31-59` — `get_nodes` (Cypher)
- `backend/repositories/topology_repo.py:62-101` — `upsert_node`
- `backend/repositories/topology_repo.py:104-107` — `delete_node`
- `backend/repositories/topology_repo.py:119-124` — `get_valid_owners_and_layers`
- `backend/repositories/topology_repo.py:127-172` — `bulk_insert_node`
- `backend/repositories/topology_repo.py:185-194` — `_VALID_NODE_LABELS`, `_validate_node_label`
- `backend/models/core.py:10-46` — `Node` Pydantic
- `backend/models/user.py:16-26` — `AIPermission`
- `backend/models/user.py:28-58` — `UserPermission`
- `backend/models/audit_event.py:14-46` — `AuditEvent` table
- `backend/models/ai_chat.py:8-20` — `AIChatMessage` table
- `backend/models/ai_operation_log.py:6-29` — `AIOperationLog` table
- `backend/models/ai_guard_models.py:10-...` — `GuardResult`
- `backend/services/audit_service.py:181-209` — `record_auth_event`
- `backend/services/audit_service.py:212-245` — `record_critical_change`
- `backend/services/audit_service.py:248-264` — `record_denied`
- `backend/services/ai_guard_service.py:28-33` — `COOLDOWNS` table
- `backend/services/ai_guard_service.py:103-131` — cooldown functions
- `backend/services/ai_guard_service.py:187-300` — `check_behavioral_guards`
- `backend/services/ai_guard_service.py:303-375` — `check_bulk_detection`
- `backend/services/ai_guard_service.py:378-416` — `check_all_guards`
- `backend/services/escalation_notifier.py:21, 53-171, 174-198` — escalation registry + publish
- `backend/routers/ai.py:36` — `APIRouter(prefix="/ai", tags=["AI Chat"])`
- `backend/routers/ai.py:39-72` — `AvailabilityIntent`, `EventListIntent`, `AvailabilityBatchIntent`, `AIChatIntent`
- `backend/routers/ai.py:75-87` — `AIChatRequest`, `AIChatResponse`
- `backend/routers/ai.py:308-619` — `chat_with_ai`
- `backend/routers/catalog.py:23-73` — `/categories` CRUD
- `backend/routers/catalog.py:86-176` — `/hardware` CRUD
- `backend/routers/catalog.py:187-296` — `/owners` CRUD
- `backend/routers/permissions.py:14-18` — `GET /permissions/`
- `backend/services/ai_chat_service.py:608` — `maybe_run_harness` dispatch
- `backend/seed_roles.py:57-81` — `AI_DIAGNOSTIC` and `AI_OPERATOR` role seeds
- `backend/repositories/mqtt_mapping_repo.py:172-270` — `create_draft`
- `backend/repositories/mqtt_mapping_repo.py:386-507` — `approve`
- `frontend/components/CIEditor.tsx:6-79` — component definition + submit
- `frontend/components/CIEditor.tsx:30-40` — initial fetches (`/categories`, `/owners`, `/hardware`)
- `frontend/components/CIEditor.tsx:213-222` — Network Layer select (Categories)
- `frontend/components/CIEditor.tsx:274-346` — SNMP Agent block
- `frontend/components/AIAgentConsole.tsx:1-144` — chat UI
- `frontend/services/geminiService.ts:24-68` — `analyzeIncident` (unused dead code path)
- `frontend/services/geminiService.ts:70-99` — `chatWithAIAgent` (live path)
- `docs/AI_AGENT_GUIDE.md:1-80` — agent-facing capability contract (no create CI today)
- `openspec/specs/ai-chat-harness-guardrails/spec.md:1-100` — two-layer guard pattern
- `openspec/specs/cmdb-graph-level-of-detail/spec.md:1-...` — adjacent (overview contract for topology read)
- `openspec/specs/audit-logging/spec.md` — adjacent
- `backend/tests/test_routers_nodes.py:391-727` — POST/DELETE tests
- `backend/tests/test_routers_nodes.py:877, 1041` — AI metadata tests
- `backend/tests/test_ai_guard_service.py` — guard service tests
- `backend/tests/test_ai_chat_service.py` — chat service tests
- `frontend/components/__tests__/CIEditor.prefill.test.tsx` — frontend CI editor tests
