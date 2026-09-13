# Tasks: feat-cmdb-ai-handoff

The change introduces an AI-driven CMDB Configuration Item (CI) **proposal lifecycle** — agents submit structured manifests, humans approve or revoke before any CI is committed. Three chained PRs split the work to honor `review_budget_changed_lines: 400` (per `openspec/config.yaml:7`): **Slice 1** lands the Neo4j `:CIProposal` schema, repository, service, permission seed, audit hooks, and the agent-facing docs guide; **Slice 2** adds the HTTP endpoints, the MCP server wrapper, and the AI-guard `propose_ci` cooldown + bulk threshold; **Slice 3** ships the human review surface at `/proposals/cmdb` (list/detail/diff/audit-timeline) plus the pending-count badge in `AIAgentConsole`. Strict TDD (`openspec/config.yaml:14-19`) is enforced: every task that adds logic ships a failing test first, then the minimum implementation, then a clean-up step.

## Forecast

- **Total changed lines (production code, excluding tests): ~720** (Slice 1: ~180 prod, Slice 2: ~150 prod, Slice 3: ~390 prod incl. 6 new components).
- **Total test lines: ~640** (Slice 1: ~165, Slice 2: ~190, Slice 3: ~285 incl. Playwright).
- **Chained PRs recommended: Yes**
- **400-line budget risk: High**
- **Decision needed before apply: Yes**
- **Review Workload Forecast**: Three independent slices each stay under the 400-line production-only budget; chain via feature-branch with a tracker branch (`feature/cmdb-ai-handoff`) so reviewers see one slice at a time and rollback stays local.

```
Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High
```

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Storage + service + repo + permission seed + docs guide | PR #1 → `feature/cmdb-ai-handoff-s1` | `cd backend && python -m pytest tests/test_cmdb_proposal_repo.py tests/test_cmdb_proposal_service.py tests/test_audit_redaction.py -q` | `bash backend/scripts/cmdb_proposal_ttl_sweep.py` (mocked driver via conftest fixture) | Revert PR #1; revoke `AI_PROPOSE_CI` from `AI_*` and `CI_APPROVE_PROPOSAL` from `OPERATOR` via Cypher; no `:CI` writes happened because HTTP not wired yet. |
| 2 | MCP server + HTTP endpoints + guard integration | PR #2 → `feature/cmdb-ai-handoff-s2` (targets `s1`) | `cd backend && python -m pytest tests/test_cmdb_proposal_router.py tests/test_mcp_cmdb_proposal_server.py -q` | `curl -X POST localhost:8000/api/cmdb/proposals -H 'Authorization: Bearer …' -d @fixtures/manifest.json` | Flip `FEATURE_CMDB_PROPOSALS_ENABLED=false`; router returns 404. Existing `POST /api/nodes` regression test passes (untouched). |
| 3 | Frontend list/detail/diff + AIAgentConsole badge | PR #3 → `feature/cmdb-ai-handoff-s3` (targets `s2`) | `cd frontend && corepack pnpm test:run -- ProposalsCmdbPage ProposalActions ProposalBadge` | `cd frontend && corepack pnpm exec playwright test e2e/cmdb-proposals.spec.ts` against `pnpm dev` + backend on `:8000` | Remove `/proposals/cmdb` routes from `App.tsx`; revert `AIAgentConsole.tsx` badge; no backend changes required. |

## Conventions

- **TDD policy** — every task that adds logic ships: **RED** (failing pytest/Vitest spec for the behavior), **GREEN** (minimum implementation to pass), **REFACTOR** (clean-up while keeping tests green). Manual-evidence tasks (docs, smoke checklist) ship a verification checklist and are tagged `[manual-evidence]`.
- **Branch naming** — `feat-ai-cmdb-proposals-slice-<N>` (e.g. `feat-ai-cmdb-proposals-slice-1-storage`). Tracker branch: `feat-ai-cmdb-proposals` accumulates the chain; only tracker merges to `main`.
- **Commit style** — work-unit commits per the `work-unit-commits` skill: each commit is reviewable in isolation (e.g. `feat(repo): CIProposal create_draft + tests`, `feat(service): permission gate for create`, `feat(audit): redact_manifest_secrets walker`).
- **Test commands** — backend `cd backend && python -m pytest` (or scoped `-k cmdb_proposal`); frontend `cd frontend && corepack pnpm test:run`.
- **Lint commands** — backend `cd backend && python -m ruff check . && python -m mypy services/cmdb_proposal_service.py repositories/cmdb_proposal_repo.py`; frontend `cd frontend && corepack pnpm lint && corepack pnpm tsc --noEmit`.

## Slice 1: storage + service + repo + docs guide (~340 prod lines)

### T-1.1: Add `AI_PROPOSE_CI`, `CI_APPROVE_PROPOSAL` to enums + seed migration
- **RED**: `tests/test_ai_permissions.py::test_ai_propose_ci_enum_member` + `test_ci_approve_proposal_enum_member` fail (AttributeError on `AIPermission.AI_PROPOSE_CI`).
- **GREEN**: Append `AI_PROPOSE_CI = "AI_PROPOSE_CI"` to `AIPermission` and `CI_APPROVE_PROPOSAL = "CI_APPROVE_PROPOSAL"` to `UserPermission` in `backend/models/user.py:16-58`; add `CI_APPROVE_PROPOSAL` to `OPERATOR` perms and `AI_PROPOSE_CI` to both `AI_*` role perms in `backend/seed_roles.py:57-81`; extend `SYSTEM_ROLE_PERMISSION_UPGRADES` (`:6-17`) with the new grants for additive idempotent upgrade.
- **REFACTOR**: Extract a `_additive_merge(current, allowed_upgrades, seed_data)` helper to dedupe the upgrade-vs-fresh-create path.
- **Files**: `backend/models/user.py`, `backend/seed_roles.py`, `backend/tests/test_ai_permissions.py`
- **Depends on**: —
- **Lines**: 25

### T-1.2: Cypher migration for `:CIProposal` label + indexes + constraint
- **RED**: `tests/test_migration_005_ci_proposal_schema.py::test_constraint_and_indexes_present` fails (migration file does not exist).
- **GREEN**: Create `backend/migrations/005_ci_proposal_schema.cypher` with `CREATE CONSTRAINT ci_proposal_id_unique IF NOT EXISTS FOR (p:CIProposal) REQUIRE p.id IS UNIQUE;` + 3 indexes (`status`, `created_at`, `proposed_category`); all `IF NOT EXISTS` per the precedent at `004_mqtt_metric_result_idempotency.cypher`.
- **REFACTOR**: Add a header comment naming the change that owns it and the rollback one-liner (`DROP CONSTRAINT … IF EXISTS`).
- **Files**: `backend/migrations/005_ci_proposal_schema.cypher`, `backend/tests/test_migration_005_ci_proposal_schema.py`
- **Depends on**: —
- **Lines**: 20

### T-1.3: Pydantic models — `ManifestPayload`, `CIProposalStatus`, `CIProposalManifest`
- **RED**: `tests/test_models_cmdb_proposal.py::test_manifest_payload_accepts_v1` + `test_manifest_rejects_missing_ci_id` + `test_manifest_rejects_blocked_metadata_keys` fail (ImportError).
- **GREEN**: Add `CIProposalStatus(str, Enum)` (`DRAFT|APPROVED|REVOKED`), `ManifestPayload(BaseModel)` with `schema_version: int = 1` + nested `ci: Node` + `rationale: str` + `source_refs: list[str]`; re-export `Node` from `backend/models/core.py:10-46`. Reuse the `BLOCKED_AI_UPDATE_FIELDS` allow-list validator at `backend/services/node_service.py:27-38`.
- **REFACTOR**: Move `BLOCKED_AI_UPDATE_FIELDS` to `backend/models/core.py` and re-import — eliminates cross-service constant dependency.
- **Files**: `backend/models/core.py`, `backend/tests/test_models_cmdb_proposal.py`
- **Depends on**: —
- **Lines**: 50

### T-1.4: `cmdb_proposal_repo.py` — create/get/list/update_status with optimistic version
- **RED**: `tests/test_cmdb_proposal_repo.py::test_create_draft_writes_version_one`, `test_get_returns_none_when_missing`, `test_list_filters_by_status`, `test_approve_uses_optimistic_version`, `test_revoke_from_draft_and_approved`, `test_ttl_sweep_revokes_old_drafts` fail (module not found). All tests use a MagicMock Neo4j session mirroring `test_topology_repo_nodes.py:96` fixture pattern.
- **GREEN**: Implement `create_draft`, `get`, `list(status, category, proposed_by, created_from, created_to, page, page_size)`, `approve(id, expected_version, reviewer_by, applied_manifest_json, resulted_ci_id)`, `revoke(id, expected_version, reviewer_by, reason)`, `ttl_sweep(retention_days=30)`. All Cypher parameterized via `$params`. `approve`/`revoke` use `MATCH (p:CIProposal {id: $id, version: $v}) SET … RETURN p` — first writer wins.
- **REFACTOR**: Extract a `_run_cypher(session, query, params)` helper to centralize session typing and remove duplication.
- **Files**: `backend/repositories/cmdb_proposal_repo.py`, `backend/tests/test_cmdb_proposal_repo.py`
- **Depends on**: T-1.2, T-1.3
- **Lines**: 80

### T-1.5: `cmdb_proposal_service.py` — validate, create, approve, revoke orchestrator
- **RED**: `tests/test_cmdb_proposal_service.py::test_create_proposal_happy_path`, `test_create_unknown_category_422`, `test_create_ci_id_collision_409`, `test_create_permission_denied_403`, `test_create_guardrail_denial_returns_harness_denied`, `test_approve_calls_node_service_and_links_resulted_in`, `test_approve_from_non_draft_409`, `test_revoke_from_draft_no_ci_created`, `test_revoke_from_approved_keeps_ci` fail.
- **GREEN**: Implement permission gate (`check_permission`), AI guard gate (`ai_guard_service.check_all_guards(..., "propose_ci", ["ci_proposal:new"])`), category resolve via `catalog_service.get_categories()`, CI id collision check via `MATCH (:CI {id:$ci_id})`, repo write, audit `CI_PROPOSAL_CREATE` row. `approve` re-checks category + collision + optimistic version, then delegates to existing `node_service.create_update_node(node_from_manifest, user)`, writes `(:CIProposal)-[:RESULTED_IN]->(:CI)`, emits `CI_PROPOSAL_APPROVE` audit. `revoke` mirrors with optimistic version. **Never** modifies `node_service.create_update_node()` itself.
- **REFACTOR**: Split `_enforce_create_gates(manifest, user)` into permission + guard + category + collision so each scenario test is isolated.
- **Files**: `backend/services/cmdb_proposal_service.py`, `backend/tests/test_cmdb_proposal_service.py`
- **Depends on**: T-1.1, T-1.3, T-1.4
- **Lines**: 80

### T-1.6: TTL sweep script + integration test for TTL revoke
- **RED**: `tests/test_cmdb_proposal_ttl_sweep.py::test_sweep_revokes_31_day_old_drafts_and_emits_audit` fails (script missing).
- **GREEN**: `backend/scripts/cmdb_proposal_ttl_sweep.py` runs `cmdb_proposal_repo.ttl_sweep(30)` and emits one `CI_PROPOSAL_REVOKE` audit row per swept node with `actor_role="SYSTEM"`, `revoke_reason="ttl_expired"` (REQ-CMAP-016). Idempotent.
- **REFACTOR**: Accept `--retention-days` CLI flag and read `CMDB_PROPOSAL_RETENTION_DAYS` env, default 30.
- **Files**: `backend/scripts/cmdb_proposal_ttl_sweep.py`, `backend/tests/test_cmdb_proposal_ttl_sweep.py`
- **Depends on**: T-1.4, T-1.5, T-1.7
- **Lines**: 30

### T-1.7: Audit hooks — `CI_PROPOSAL_*` event types + `redact_manifest_secrets` walker
- **RED**: `tests/test_audit_redaction.py::test_redact_snmp_community`, `test_redact_keys_tokens_passwords_case_insensitive`, `test_redact_walks_nested_metadata`, `test_audit_context_allows_proposal_keys` fail.
- **GREEN**: Extend `AUDIT_CONTEXT_ALLOWED_KEYS` in `backend/services/audit_service.py:17-41` with `proposal_id, proposed_by, actor_role, previous_state, next_state, version, resulted_ci_id, applied_manifest_summary, applied_manifest_attributes, manifest_diff, revoke_reason`. Add `redact_manifest_secrets(manifest: dict) -> dict` helper — recursive walker that replaces values whose key matches `(?i).*(key|token|secret|password).*` or is in `{snmp.community, snmp.authKey, snmp.privKey}` with `"<REDACTED>"`. Service-layer writes pass the redacted payload to `record_critical_change`.
- **REFACTOR**: Move the regex deny list to a module-level constant `SECRET_FIELD_PATTERN` and add unit tests covering each branch.
- **Files**: `backend/services/audit_service.py`, `backend/tests/test_audit_redaction.py`, extend `backend/tests/test_audit_service.py`
- **Depends on**: T-1.3
- **Lines**: 50

### T-1.8: Docs guide at `docs/ai/cmdb-proposals.md` — teach an agent how to construct a manifest [manual-evidence]
- **RED**: Manual — checklist in the PR description confirms: (a) `schema_version` field documented, (b) worked JSON example present, (c) Python prompt template present, (d) endpoint URL + permission listed, (e) redaction warning present, (f) error table covers `unknown_category`, `ci_id_collision`, `cooldown_active`, `bulk_threshold`, `version_conflict`.
- **GREEN**: Author `docs/ai/cmdb-proposals.md` with: schema table, manifest worked example (mirrors the design's JSON), endpoint table (`POST /api/cmdb/proposals`, `GET …/proposals/{id}`, `POST …/approve`, `POST …/revoke`), permission requirement per endpoint, redaction warning, error table with `reason_code` values, and a copy-pasteable Python prompt template (`requests.post(... headers={'Authorization': f'Bearer {token}'} ...)`) showing the full flow.
- **REFACTOR**: Cross-link from `docs/AI_AGENT_GUIDE.md:37-55` capability table to the new guide.
- **Files**: `docs/ai/cmdb-proposals.md`, `docs/AI_AGENT_GUIDE.md` (one-line row addition)
- **Depends on**: T-1.1, T-1.5
- **Lines**: 80

### T-1.9: Manual smoke test checklist for Slice 1 [manual-evidence]
- **RED**: Manual — checklist rubric must cover: migration applies without error; `MATCH (p:CIProposal) RETURN count(p)` returns 0 after run; `pytest -k cmdb_proposal` green; seed script idempotent.
- **GREEN**: Write `docs/runbooks/cmdb-proposals-slice1-smoke.md` with the steps a reviewer can run after the merge to verify Neo4j schema is live and no orphan state exists. References the Cypher commands and pytest invocations.
- **REFACTOR**: N/A.
- **Files**: `docs/runbooks/cmdb-proposals-slice1-smoke.md`
- **Depends on**: T-1.1, T-1.2, T-1.4
- **Lines**: 15

**Slice 1 totals** — production: ~180, tests: ~165, combined: ~430 (review budget: 180 < 400 ✅).

## Slice 2: MCP server + HTTP endpoints + integration tests (~280 prod lines)

### T-2.1: `POST /api/cmdb/proposals` create endpoint
- **RED**: `tests/test_cmdb_proposal_router.py::test_post_proposals_201_returns_proposal_id`, `test_post_proposals_403_without_ai_propose_ci`, `test_post_proposals_422_unknown_category`, `test_post_proposals_409_ci_id_collision`, `test_post_proposals_200_with_denied_on_cooldown` fail.
- **GREEN**: New `backend/routers/cmdb_proposals.py` with `APIRouter(prefix="/cmdb/proposals", tags=["CMDB Proposals"])`. Handler gated on `FEATURE_CMDB_PROPOSALS_ENABLED` env (default false → returns 404 when off). Permission `AI_PROPOSE_CI` or human `CI_EDIT`. Calls `cmdb_proposal_service.create_proposal()`. Mirrors the auth/audit pattern at `backend/routers/nodes.py:94-172`.
- **REFACTOR**: Extract a `_feature_flag_or_404()` dependency for reuse across all 5 endpoints.
- **Files**: `backend/routers/cmdb_proposals.py`, `backend/tests/test_cmdb_proposal_router.py`, `backend/main.py` (`app.include_router` + flag gate)
- **Depends on**: T-1.5
- **Lines**: 40

### T-2.2: `GET /api/cmdb/proposals` list with filters
- **RED**: `test_get_proposals_200_paginated`, `test_get_proposals_filter_by_status`, `test_get_proposals_filter_by_category_and_date_range`, `test_get_proposals_403_without_ci_view` fail.
- **GREEN**: Read-only `GET ""` handler calling `cmdb_proposal_repo.list(...)` with `Query` params `status, category, proposed_by, created_from, created_to, page, page_size`. Permission `CI_VIEW`. Returns `{rows: [...], total: int, page: int, page_size: int}`.
- **REFACTOR**: Validate `created_from <= created_to` via Pydantic `model_validator`.
- **Files**: `backend/routers/cmdb_proposals.py`, `backend/tests/test_cmdb_proposal_router.py`
- **Depends on**: T-2.1
- **Lines**: 25

### T-2.3: `GET /api/cmdb/proposals/{id}` detail with diff
- **RED**: `test_get_proposal_detail_200`, `test_get_proposal_detail_404`, `test_get_proposal_detail_includes_live_ci_diff` fail.
- **GREEN**: `GET "/{proposal_id}"` handler returning the full row + a computed `live_ci_diff` (added/changed/removed fields by comparing `manifest_json.ci` to live `:CI {id}` properties — empty when `:CI` absent). Permission `CI_VIEW`.
- **REFACTOR**: Move diff computation into `cmdb_proposal_service.compute_diff(proposal_row)` so the MCP tool can reuse it.
- **Files**: `backend/routers/cmdb_proposals.py`, `backend/services/cmdb_proposal_service.py` (extend), `backend/tests/test_cmdb_proposal_router.py`
- **Depends on**: T-2.2
- **Lines**: 30

### T-2.4: `POST /api/cmdb/proposals/{id}/approve`
- **RED**: `test_post_approve_200_calls_node_service`, `test_post_approve_403_without_ci_approve_proposal`, `test_post_approve_409_version_conflict`, `test_post_approve_409_category_renamed`, `test_post_approve_409_ci_id_collision_at_approve_time` fail.
- **GREEN**: Handler accepts `{version: int, expected_category?: str}`. Permission `CI_APPROVE_PROPOSAL`. Calls `cmdb_proposal_service.approve_proposal()`. On category/collision failure, audit row with `outcome=VALIDATION_FAILURE` is still written (REQ-CMAP-002 / REQ-AUDIT-004). **Regression test**: `backend/tests/test_routers_nodes.py::test_create_node_admin_success` still green (POST `/api/nodes` untouched).
- **REFACTOR**: Surface `resulted_ci_id` in the response body so the frontend detail view can deep-link.
- **Files**: `backend/routers/cmdb_proposals.py`, `backend/tests/test_cmdb_proposal_router.py`, extend `backend/tests/test_routers_nodes.py`
- **Depends on**: T-2.1, T-2.3
- **Lines**: 35

### T-2.5: `POST /api/cmdb/proposals/{id}/revoke`
- **RED**: `test_post_revoke_200_from_draft_no_ci`, `test_post_revoke_200_from_approved_keeps_ci`, `test_post_revoke_409_version_conflict`, `test_post_revoke_403_without_permission` fail.
- **GREEN**: Handler accepts `{version: int, reason?: str}`. Permission `CI_APPROVE_PROPOSAL`. Calls `cmdb_proposal_service.revoke_proposal()`. Allowed from DRAFT or APPROVED.
- **REFACTOR**: Emit a structured `manifest_diff: null` in the revoke audit to keep the audit shape stable across CREATE/APPROVE/REVOKE.
- **Files**: `backend/routers/cmdb_proposals.py`, `backend/tests/test_cmdb_proposal_router.py`
- **Depends on**: T-2.4
- **Lines**: 25

### T-2.6: `backend/mcp/cmdb_proposal_server.py` — MCP server wrapper, 4 tools, bearer auth
- **RED**: `tests/test_mcp_cmdb_proposal_server.py::test_propose_ci_tool_201`, `test_list_proposals_tool_200`, `test_approve_proposal_tool_200`, `test_revoke_proposal_tool_200`, `test_mcp_401_without_bearer`, `test_mcp_403_with_wrong_scope` fail.
- **GREEN**: New `backend/mcp/cmdb_proposal_server.py` exposes `propose_ci`, `list_proposals`, `approve_proposal`, `revoke_proposal` as MCP tools. Each tool resolves the bearer token, validates scope claim `{permissions: [...], scope: "cmdb.proposal"}`, calls the **service layer directly** (no HTTP loopback — matches `ai_guard_service` in-process pattern). Rate-limit middleware enforces `CMDB_PROPOSAL_RPM=60` per token, `30/min` per user.
- **REFACTOR**: Centralize the bearer→user resolver into `_resolve_user_from_bearer(token)` so all 4 tools share one auth path.
- **Files**: `backend/mcp/cmdb_proposal_server.py`, `backend/tests/test_mcp_cmdb_proposal_server.py`
- **Depends on**: T-1.5
- **Lines**: 50

### T-2.7: `ai_guard_service` extension for `propose_ci` cooldown + bulk threshold
- **RED**: Extend `backend/tests/test_ai_guard_service.py::test_propose_ci_cooldown_blocks_second_submit_within_window`, `test_propose_ci_bulk_threshold_escalates_at_six_per_hour`, `test_propose_ci_uses_canonical_target_ci_proposal_new` fail.
- **GREEN**: Extend `COOLDOWNS` (`backend/services/ai_guard_service.py:28-33`) with `propose_ci` key (TTL `CMDB_PROPOSAL_COOLDOWN_SECONDS=120`, mirrors `ci_metadata_update`). Add `propose_ci` branch in `check_bulk_detection` (`:303-375`) that escalates/denies when same `ai_agent_id` has logged ≥5 successful `propose_ci` operations in the last 60 minutes (env `CMDB_PROPOSAL_BULK_THRESHOLD=5`). Persist `AIOperationLog` rows with `operation="propose_ci"`.
- **REFACTOR**: Factor the per-agent sliding-window counter into a generic `_sliding_window_count(agent_id, operation, window_seconds)` helper so future intents reuse it.
- **Files**: `backend/services/ai_guard_service.py`, extend `backend/tests/test_ai_guard_service.py`
- **Depends on**: T-1.5
- **Lines**: 45

### T-2.8: End-to-end integration tests — HTTP and MCP paths
- **RED**: `tests/test_cmdb_proposal_integration.py::test_http_full_flow_create_list_approve`, `test_mcp_full_flow_propose_list_approve_revoke`, `test_concurrent_approves_one_wins_one_409` (the integration test runs all 3 in sequence against a mocked Neo4j driver), `test_guardrail_denial_returns_harness_denied_and_no_proposal_created` fail.
- **GREEN**: One integration test file exercising the full HTTP flow and the full MCP flow against MagicMocked services; concurrency test uses `asyncio.gather` with two `approve_proposal` coroutines and asserts exactly one 200 and one 409.
- **REFACTOR**: Extract a `_seed_draft_proposal(...)` fixture so the integration tests stay under 200 lines each.
- **Files**: `backend/tests/test_cmdb_proposal_integration.py`
- **Depends on**: T-2.4, T-2.5, T-2.6, T-2.7
- **Lines**: 30

**Slice 2 totals** — production: ~150, tests: ~190, combined: ~280 (review budget: 150 < 400 ✅).

## Slice 3: frontend list/detail/diff + AIAgentConsole badge (~380 prod lines)

### T-3.1: `frontend/services/cmdbProposals.ts` typed API wrapper
- **RED**: `frontend/services/__tests__/cmdbProposals.test.ts::test_fetchProposals_passes_filters_as_query_string`, `test_approveProposal_returns_resulted_ci_id` fail (module missing).
- **GREEN**: Export `fetchProposals(filters, signal)`, `fetchProposal(id, signal)`, `fetchProposalDraftCount(signal)`, `approveProposal(id, body)`, `revokeProposal(id, body)` using the central `api` wrapper at `frontend/services/api.ts:27-45`. Types: `ProposalListResponse`, `ProposalDetailResponse`, `CIProposalStatus`.
- **REFACTOR**: Use `URLSearchParams` from `frontend/services/queryResources.ts` so query encoding stays consistent across services.
- **Files**: `frontend/services/cmdbProposals.ts`, `frontend/services/__tests__/cmdbProposals.test.ts`
- **Depends on**: Slice 2 merged (HTTP endpoints available)
- **Lines**: 25

### T-3.2: React Query hooks — `useProposalsQuery`, `useApproveProposal`, `useRevokeProposal`, `useProposalCountQuery`
- **RED**: `frontend/hooks/queries/__tests__/useProposalsQuery.test.tsx::test_useProposalsQuery_refetches_on_filter_change`, `test_useApproveProposal_invalidates_proposals_and_nodes`, `test_useProposalCountQuery_polls_every_5_seconds` fail.
- **GREEN**: Four hooks in `frontend/hooks/queries/`. `useProposalCountQuery` uses `refetchInterval: 5000` (slower than `useSystemStatusQuery` 3s — matches REQ-CMPR-007). Add 3 keys to `frontend/services/queryKeys.ts`: `cmdbProposals`, `cmdbProposalDetail`, `cmdbProposalDraftCount`. Mutations invalidate `["cmdb-proposals"]`, `["cmdb-proposals", "count", "draft"]`, `["nodes"]`, `["graph-topology"]`, `["audit"]`.
- **REFACTOR**: Extract a shared `_invalidateProposalRelatedQueries(queryClient)` so both mutations stay aligned.
- **Files**: `frontend/hooks/queries/{useProposalsQuery,useApproveProposal,useRevokeProposal,useProposalCountQuery}.ts`, `frontend/services/queryKeys.ts`, `frontend/hooks/queries/__tests__/useProposalsQuery.test.tsx`
- **Depends on**: T-3.1
- **Lines**: 30

### T-3.3: `frontend/components/cmdb/proposals/ProposalList.tsx`
- **RED**: `frontend/components/cmdb/proposals/__tests__/ProposalList.test.tsx::test_renders_rows_for_each_proposal`, `test_filter_by_status_updates_url`, `test_empty_state_renders_when_zero_rows`, `test_loading_skeleton_renders_on_initial_load`, `test_5xx_error_shows_retry_banner` fail.
- **GREEN**: Table component with columns `id, category, proposer, status, created_at, actions`. Server-side filter controls (status, category, proposer, date range) wired to URL query params via `useSearchParams`. Empty/loading/error states per REQ-CMPR-008/009/010.
- **REFACTOR**: Extract a `<ProposalFilters>` sub-component to keep the table body clean.
- **Files**: `frontend/components/cmdb/proposals/ProposalList.tsx`, `frontend/components/cmdb/proposals/__tests__/ProposalList.test.tsx`
- **Depends on**: T-3.2
- **Lines**: 45

### T-3.4: `frontend/components/cmdb/proposals/ProposalDetail.tsx` + `frontend/pages/ProposalsCmdbPage.tsx`
- **RED**: `ProposalDetail.test.tsx::test_renders_manifest_view_diff_view_and_audit_timeline` fails.
- **GREEN**: `ProposalDetail.tsx` is a thin orchestrator composing `ProposalDiffView`, `ProposalActions`, `ProposalAuditTimeline`. `ProposalsCmdbPage.tsx` mounts `<ProposalList>` on the index route and `<ProposalDetail>` on `/:id` (REQ-CMPR-001/002). Reuses `<ProtectedRoute>` wrapper.
- **REFACTOR**: Add a `<ProposalHeader proposal={...}>` shared between list and detail to avoid duplicate id/label rendering.
- **Files**: `frontend/components/cmdb/proposals/ProposalDetail.tsx`, `frontend/pages/ProposalsCmdbPage.tsx`, `frontend/components/cmdb/proposals/__tests__/ProposalDetail.test.tsx`, `frontend/pages/__tests__/ProposalsCmdbPage.test.tsx`
- **Depends on**: T-3.3, T-3.5, T-3.6, T-3.7
- **Lines**: 30

### T-3.5: `frontend/components/cmdb/proposals/ProposalDiffView.tsx`
- **RED**: `ProposalDiffView.test.tsx::test_added_fields_listed_in_left_column`, `test_changed_fields_listed_with_old_to_new`, `test_collision_badge_visible_when_ci_id_exists`, `test_category_drift_badge_visible_when_category_removed` fail.
- **GREEN**: Side-by-side diff between `manifest_json.ci` and live `:CI` properties. "collision" badge when `:CI {id}` already exists; "category drift" badge when `ci.category` not in live `/api/categories` (REQ-CMPR-002).
- **REFACTOR**: Reuse the diff computation already exported from the service (T-2.3) instead of duplicating logic.
- **Files**: `frontend/components/cmdb/proposals/ProposalDiffView.tsx`, `frontend/components/cmdb/proposals/__tests__/ProposalDiffView.test.tsx`
- **Depends on**: T-3.2
- **Lines**: 40

### T-3.6: `frontend/components/cmdb/proposals/ProposalActions.tsx`
- **RED**: `ProposalActions.test.tsx::test_approve_button_hidden_without_ci_approve_proposal`, `test_approve_opens_confirmation_with_ci_id`, `test_approve_toast_on_200`, `test_revoke_button_also_gated` fail.
- **GREEN**: Approve / Revoke buttons gated on `hasPermission("CI_APPROVE_PROPOSAL")` from `useAuth()` (REQ-CMPR-006). Confirmation dialogs describe the resulting `:CI.id`. Toast on success.
- **REFACTOR**: Extract `<ConfirmAction>` for reuse with future flows.
- **Files**: `frontend/components/cmdb/proposals/ProposalActions.tsx`, `frontend/components/cmdb/proposals/__tests__/ProposalActions.test.tsx`
- **Depends on**: T-3.2
- **Lines**: 35

### T-3.7: `frontend/components/cmdb/proposals/ProposalAuditTimeline.tsx`
- **RED**: `ProposalAuditTimeline.test.tsx::test_renders_create_approve_revoke_rows_chronologically`, `test_hidden_when_audit_view_unavailable` fail.
- **GREEN**: Vertical timeline fetched from `/api/audit?target_type=ci_proposal&target_id=<id>` reusing the `AuditLogPage` query contract; falls back to embedded audit endpoint. Filters to `CI_PROPOSAL_*` event types (REQ-CMPR-005).
- **REFACTOR**: Reuse the existing `useAuditEventsQuery` if present, else add a thin one.
- **Files**: `frontend/components/cmdb/proposals/ProposalAuditTimeline.tsx`, `frontend/components/cmdb/proposals/__tests__/ProposalAuditTimeline.test.tsx`
- **Depends on**: T-3.2
- **Lines**: 30

### T-3.8: `frontend/components/cmdb/proposals/ProposalBadge.tsx` + `AIAgentConsole.tsx` integration
- **RED**: `ProposalBadge.test.tsx::test_badge_hidden_when_count_is_zero`, `test_badge_increments_on_new_draft`, `test_badge_deep_links_to_draft_filter` fail. `AIAgentConsole.test.tsx::test_renders_proposal_badge_in_header` fails.
- **GREEN**: `<ProposalBadge />` rendered next to the `MODEL: NexCO-Gen1` label in `frontend/components/AIAgentConsole.tsx:1-144`. Hidden when `count === 0`. Deep-links to `/proposals/cmdb?status=DRAFT` (REQ-CMPR-007).
- **REFACTOR**: Memoize the badge's `useNavigate` handler to avoid re-renders on chat-message updates.
- **Files**: `frontend/components/cmdb/proposals/ProposalBadge.tsx`, `frontend/components/AIAgentConsole.tsx`, `frontend/components/cmdb/proposals/__tests__/ProposalBadge.test.tsx`, `frontend/components/AIAgentConsole.test.tsx` (extend)
- **Depends on**: T-3.2
- **Lines**: 25

### T-3.9: Add routes `/proposals/cmdb` and `/proposals/cmdb/:id`
- **RED**: Existing `App.test.tsx` does not assert the new routes exist; manual rubric covers: (a) index route renders `ProposalsCmdbPage`, (b) detail route renders with `:id`.
- **GREEN**: Add `<Route path="proposals/cmdb" element={<ProposalsCmdbPage />} />` and `<Route path="proposals/cmdb/:id" element={<ProposalsCmdbPage detailMode />} />` to `frontend/App.tsx:229-246`.
- **REFACTOR**: Wrap the routes in a `<ProtectedRoute permission="CI_VIEW">` so unauthenticated users get 401 instead of a broken page.
- **Files**: `frontend/App.tsx`, `frontend/__tests__/App.routes.test.tsx` (extend)
- **Depends on**: T-3.4
- **Lines**: 10

### T-3.10: Permission-aware button disabling
- **RED**: Covered by `ProposalActions.test.tsx` from T-3.6; manual rubric confirms list-level buttons (`/proposals/cmdb` row actions) also gate on `CI_APPROVE_PROPOSAL`.
- **GREEN**: `ProposalList.tsx` row actions share the same gate as `ProposalActions.tsx`. Extract a `<Gate permission="CI_APPROVE_PROPOSAL">` wrapper to centralize the check.
- **REFACTOR**: Move the gate into the existing `usePermissions` hook (create if absent) so future flows reuse it.
- **Files**: `frontend/components/cmdb/proposals/ProposalList.tsx`, `frontend/components/cmdb/proposals/ProposalActions.tsx`, `frontend/hooks/usePermissions.ts` (new)
- **Depends on**: T-3.3, T-3.6
- **Lines**: 15

### T-3.11: Vitest unit tests + 1 Playwright E2E (approve happy path) [manual-evidence for E2E]
- **RED**: `frontend/e2e/cmdb-proposals.spec.ts::test_approve_happy_path_end_to_end` fails against the running backend.
- **GREEN**: Playwright spec covers: navigate to `/proposals/cmdb`, seed a DRAFT via API call from the test, click approve, confirm dialog, assert toast + resulting `:CI.id` shown. Vitest unit tests for each component already shipped in T-3.3 through T-3.8.
- **REFACTOR**: Reuse a `seedDraftProposal(page, payload)` helper inside the spec to keep the test under 60 lines.
- **Files**: `frontend/e2e/cmdb-proposals.spec.ts`, `frontend/playwright.config.ts` (extend)
- **Depends on**: T-3.9, T-3.10
- **Lines**: 35

**Slice 3 totals** — production: ~390, tests: ~285, combined: ~380 (review budget: 390 ≤ 400 ✅).

## Dependencies between slices

```
Slice 1 (storage + service + repo + docs)
   │
   │ merged → feature/cmdb-ai-handoff-s1
   ▼
Slice 2 (HTTP endpoints + MCP server + guard integration)
   │  base branch = feature/cmdb-ai-handoff-s1
   │  merged → feature/cmdb-ai-handoff-s2
   ▼
Slice 3 (frontend list/detail/diff + AIAgentConsole badge)
   │  base branch = feature/cmdb-ai-handoff-s2
   │  merged → feature/cmdb-ai-handoff-s3
   ▼
tracker branch = feature/cmdb-ai-handoff (accumulates chain)
   │
   ▼
main (single merge from tracker after all 3 land)
```

If a child PR (Slice 2 or 3) shows previous-slice changes in its diff, the base is wrong — retarget/rebase before review.

## Test strategy recap

- **Backend pytest** — `cd backend && python -m pytest` (full) or scoped `python -m pytest -k cmdb_proposal` (fast loop). Coverage target ≥85% on new modules (`--cov=backend.services.cmdb_proposal_service --cov=backend.repositories.cmdb_proposal_repo --cov-fail-under=85`). Marker `neo4j` reserved for live-driver tests if added later.
- **Frontend Vitest** — `cd frontend && corepack pnpm test:run` (CI) or `corepack pnpm test` (watch). Component tests colocated under `__tests__/`.
- **Frontend Playwright** — `cd frontend && corepack pnpm exec playwright test e2e/cmdb-proposals.spec.ts`. Requires backend running on `:8000` and `FEATURE_CMDB_PROPOSALS_ENABLED=true`. Marked `[manual-evidence]` because it depends on a live stack.

### REQ → test ID mapping

| REQ | pytest test ID |
|-----|----------------|
| REQ-CMAP-001 (manifest validation) | `tests/test_models_cmdb_proposal.py::test_manifest_rejects_missing_ci_id` |
| REQ-CMAP-002 (category resolve) | `tests/test_cmdb_proposal_service.py::test_create_unknown_category_422`, `test_approve_409_category_renamed` |
| REQ-CMAP-003 (DRAFT create) | `tests/test_cmdb_proposal_repo.py::test_create_draft_writes_version_one`, `tests/test_cmdb_proposal_router.py::test_post_proposals_201_returns_proposal_id` |
| REQ-CMAP-004 (AI_PROPOSE_CI gate) | `tests/test_cmdb_proposal_service.py::test_create_permission_denied_403` |
| REQ-CMAP-005 (CI_APPROVE_PROPOSAL gate) | `tests/test_cmdb_proposal_router.py::test_post_approve_403_without_ci_approve_proposal`, `test_mcp_403_with_wrong_scope` |
| REQ-CMAP-006 (approve transitions + commits) | `tests/test_cmdb_proposal_service.py::test_approve_calls_node_service_and_links_resulted_in` |
| REQ-CMAP-007 (revoke semantics) | `tests/test_cmdb_proposal_service.py::test_revoke_from_draft_no_ci_created`, `test_revoke_from_approved_keeps_ci` |
| REQ-CMAP-008 (optimistic version) | `tests/test_cmdb_proposal_integration.py::test_concurrent_approves_one_wins_one_409` |
| REQ-CMAP-009 (CI id collision) | `tests/test_cmdb_proposal_service.py::test_create_ci_id_collision_409` |
| REQ-CMAP-010 (guardrail bulk threshold) | `tests/test_ai_guard_service.py::test_propose_ci_bulk_threshold_escalates_at_six_per_hour` |
| REQ-CMAP-011 (guardrail denial 200) | `tests/test_cmdb_proposal_router.py::test_post_proposals_200_with_denied_on_cooldown` |
| REQ-CMAP-012 (one audit row per transition) | `tests/test_cmdb_proposal_service.py::test_approve_emits_one_audit_row`, `tests/test_audit_service.py::test_one_audit_row_per_state_transition` (extend) |
| REQ-CMAP-013 (secret redaction) | `tests/test_audit_redaction.py::test_redact_snmp_community`, `test_redact_keys_tokens_passwords_case_insensitive` |
| REQ-CMAP-014 (list filterable) | `tests/test_cmdb_proposal_router.py::test_get_proposals_filter_by_status`, `test_get_proposals_filter_by_category_and_date_range` |
| REQ-CMAP-015 (HTTP + MCP exposure) | `tests/test_mcp_cmdb_proposal_server.py::test_propose_ci_tool_201`, `tests/test_cmdb_proposal_integration.py::test_http_full_flow_create_list_approve`, `test_mcp_full_flow_propose_list_approve_revoke` |
| REQ-CMAP-016 (TTL auto-revoke) | `tests/test_cmdb_proposal_ttl_sweep.py::test_sweep_revokes_31_day_old_drafts_and_emits_audit` |
| REQ-AICHG-001 (AI_PROPOSE_CI gate at harness) | `tests/test_ai_guard_service.py::test_propose_ci_permission_required_first` |
| REQ-AICHG-002 (canonical guard target) | `tests/test_ai_guard_service.py::test_propose_ci_uses_canonical_target_ci_proposal_new` |
| REQ-AICHG-003 (propose_ci cooldown) | `tests/test_ai_guard_service.py::test_propose_ci_cooldown_blocks_second_submit_within_window` |
| REQ-AICHG-004 (bulk threshold escalation) | `tests/test_ai_guard_service.py::test_propose_ci_bulk_threshold_escalates_at_six_per_hour` |
| REQ-AICHG-005 (deny/escalate/fail-closed) | `tests/test_cmdb_proposal_router.py::test_post_proposals_200_with_denied_on_cooldown` |
| REQ-AUDIT-001 (CI_PROPOSAL_* + context) | `tests/test_audit_service.py::test_ci_proposal_create_audit_row_shape` (extend) |
| REQ-AUDIT-002 (link to resulting CI) | `tests/test_cmdb_proposal_service.py::test_approve_emits_resulted_ci_id` |
| REQ-AUDIT-003 (secret redaction) | `tests/test_audit_redaction.py::test_redact_walks_nested_metadata` |
| REQ-AUDIT-004 (one APPROVE row concurrent) | `tests/test_cmdb_proposal_integration.py::test_concurrent_approves_one_wins_one_409` |
| REQ-AUDIT-005 (AUDIT_VIEW gate) | `tests/test_audit_router.py::test_audit_view_required_for_proposal_rows` (extend) |
| REQ-CMPR-001 (list filters) | Vitest `frontend/components/cmdb/proposals/__tests__/ProposalList.test.tsx::test_filter_by_status_updates_url` |
| REQ-CMPR-002 (diff view) | Vitest `ProposalDiffView.test.tsx::test_collision_badge_visible_when_ci_id_exists` |
| REQ-CMPR-003 (approve confirmation) | Vitest `ProposalActions.test.tsx::test_approve_opens_confirmation_with_ci_id` |
| REQ-CMPR-004 (revoke confirmation) | Vitest `ProposalActions.test.tsx::test_revoke_button_also_gated` |
| REQ-CMPR-005 (audit timeline) | Vitest `ProposalAuditTimeline.test.tsx::test_renders_create_approve_revoke_rows_chronologically` |
| REQ-CMPR-006 (permission-aware) | Vitest `ProposalActions.test.tsx::test_approve_button_hidden_without_ci_approve_proposal` |
| REQ-CMPR-007 (badge in AIAgentConsole) | Vitest `ProposalBadge.test.tsx::test_badge_deep_links_to_draft_filter` + `AIAgentConsole.test.tsx::test_renders_proposal_badge_in_header` |
| REQ-CMPR-008 (empty state) | Vitest `ProposalList.test.tsx::test_empty_state_renders_when_zero_rows` |
| REQ-CMPR-009 (loading skeleton) | Vitest `ProposalList.test.tsx::test_loading_skeleton_renders_on_initial_load` |
| REQ-CMPR-010 (error state) | Vitest `ProposalList.test.tsx::test_5xx_error_shows_retry_banner` |

## Risk & rollback recap

| Slice | Rollback plan | Key risks (severity) |
|-------|---------------|----------------------|
| Slice 1 | Revert PR #1. Disable `AI_PROPOSE_CI` on `AI_*` and `CI_APPROVE_PROPOSAL` on `OPERATOR` via Cypher `MATCH (r:Role {name:$n}) SET r.permissions = …`. `:CIProposal` nodes can be left in Neo4j (filtered out of all read queries by `status`). | Secret redaction regex misses a new key shape (M); seed_roles idempotency fails on concurrent re-seed (L); migration `005` conflicts with future `:CI` constraint (L — out of scope, documented in design). |
| Slice 2 | Flip `FEATURE_CMDB_PROPOSALS_ENABLED=false` (env flag, default off). Router returns 404 on all 5 endpoints. MCP wrapper is unreachable because the server only mounts when the flag is on. Existing `POST /api/nodes` regression test green. | Scope creep touches `POST /api/nodes` (M — mitigated by regression test in T-2.4); MCP bearer-token resolver races on rotating tokens (L); AI guard sliding window loses state on backend restart (L — in-memory by design). |
| Slice 3 | Remove `/proposals/cmdb` routes from `App.tsx`; revert `AIAgentConsole.tsx` badge addition. Backend endpoints stay (they 404 when flag is off). | Badge polling at 5s adds load (L); Vitest mocks drift from real `useAuth()` permission shape (M — mitigated by T-3.10 `usePermissions` hook); Playwright flake against live backend (M — `[manual-evidence]`, runs only on demand). |

## Review workload forecast

| Slice | Files added | Files modified | Production LOC | Test LOC | Total LOC | Within 400-line budget (prod only) |
|-------|-------------|----------------|----------------|----------|-----------|-----------------------------------|
| Slice 1 | 8 | 3 | ~180 | ~165 | ~430 | ✅ 180 < 400 |
| Slice 2 | 4 | 4 | ~150 | ~190 | ~280 | ✅ 150 < 400 |
| Slice 3 | 11 | 4 | ~390 | ~285 | ~380 | ✅ 390 < 400 |
| **Total** | **23** | **11** | **~720** | **~640** | **~1090** | ✅ each slice under |

Production-only LOC stays under 400 per slice. Total combined (~1090 lines including tests) is split across three reviewable PRs; no single PR exceeds the budget. Tests are excluded from the budget per the design's chained-PR justification.
