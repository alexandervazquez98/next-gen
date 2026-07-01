# Verification Report: feat-324-vpn-sdwan-satellite-link-simulation — Slice 1

## Scope

Slice-level verification for **Slice 1: Data Model + Catalog Primitives** only. Slice 2 polling/health and Slice 3 visual/filter work were explicitly out of scope and were checked for drift.

## Fresh test evidence

### Backend touched tests

Command requested: `cd backend && python -m pytest tests/test_topology_repo_nodes.py tests/test_topology_relationships.py tests/test_routers_links.py`

Environment note: the worktree `/usr/bin/python` has no `pytest`; verification installed dependencies into `/tmp/opencode/next-gen-backend-verify-324` and re-ran the same pytest target with that venv on `PATH`.

Effective command:

```text
cd backend && PATH=/tmp/opencode/next-gen-backend-verify-324/bin:$PATH python -m pytest tests/test_topology_repo_nodes.py tests/test_topology_relationships.py tests/test_routers_links.py
```

Outcome:

```text
collected 51 items
tests/test_topology_repo_nodes.py ..............
tests/test_topology_relationships.py ...................
tests/test_routers_links.py ..................
======================== 51 passed, 6 warnings in 1.36s ========================
```

### Frontend full suite

Command:

```text
cd frontend && corepack pnpm test:run
```

Outcome:

```text
Test Files  58 passed (58)
Tests       490 passed (490)
Duration    12.68s
```

## Spec coverage table — Slice 1 only

| # | Scenario | Covering test/evidence | Status |
|---|---|---|---|
| 1 | Save CI with valid `public_ip` | `test_node_model_accepts_valid_public_ip`, `test_node_model_accepts_ipv6_public_ip`, `test_upsert_node_persists_public_ip`; `Node.public_ip` field and `upsert_node` SET verified in source | ✅ COMPLIANT |
| 2 | Reject invalid `public_ip` | `test_node_model_rejects_invalid_public_ip`, `test_create_update_node_rejects_invalid_public_ip`; service returns HTTP 400 before `upsert_node` | ✅ COMPLIANT |
| 3 | Existing CIs are not backfilled | `test_node_model_allows_missing_public_ip`, `test_upsert_node_passes_none_when_public_ip_missing`; no migration/backfill path added | ✅ COMPLIANT |
| 4 | Create tunnel relation medium | `test_link_model_accepts_medium`, `test_link_model_accepts_satellite_medium`, `test_create_link_persists_medium`, `test_get_links_returns_medium_in_payload`, `test_list_links_exposes_medium_when_set` | ✅ COMPLIANT |
| 5 | Reject unsupported medium | `test_validate_tunnel_endpoint_hub_rejects_unsupported_medium`; `Link.medium` Literal validator | ✅ COMPLIANT |
| 6 | Hub-to-remote tunnel is valid | `test_validate_tunnel_endpoint_hub_accepts_hub_to_remote` | ✅ COMPLIANT |
| 7 | Non-hub tunnel is rejected | `test_validate_tunnel_endpoint_hub_rejects_non_hub`, `test_create_link_service_runs_hub_validation`, `test_create_tunnel_link_rejected_without_vpn_hub_endpoint` | ✅ COMPLIANT |
| 8 | Graph payload includes tunnel metadata | `test_full_graph_exposes_medium_on_tunnel_links`, `test_full_graph_does_not_change_node_status_or_event_fields`, `test_get_links_omits_medium_when_unset` | ✅ COMPLIANT |
| 9 | 4 new icon keys accepted as controlled keys | `categoryIcons.test.ts` controlled-key test; `types.test.ts` CategoryIconKey test | ✅ COMPLIANT |
| 10 | Catalog exposes 4 entries with non-empty fixed symbols | `categoryIcons.test.ts` fixed symbol assertions; source uses `vpn_key`, `hub`, `satellite_alt`, `vpn_lock` | ✅ COMPLIANT |
| 11 | Bilingual catalog discovery for each new entry | `finds each new entry by English search terms`, `finds each new entry by Spanish search terms` | ✅ COMPLIANT |
| 12 | Generic fallback preserved | `preserves the generic fallback for unrelated categories`, `falls back to generic icon for invalid icon keys` | ✅ COMPLIANT |

## Endpoint rule validation

- `backend/services/link_service.py` defines `ALLOWED_TUNNEL_MEDIUMS = frozenset({"vpn", "sd_wan", "satellite"})` and `VPN_HUB_LAYER = "vpn_hub"` as the service single source of truth.
- `validate_tunnel_endpoint_hub` is the single service enforcement point for the hub-obligatorio rule.
- The validator returns immediately when `medium` is `None` or empty, preserving non-tunnel links.
- Unsupported mediums raise `HTTPException(status_code=400)` before persistence.
- If endpoint types are missing, the validator fetches them via `topology_repo.get_endpoint_types`.
- The validator accepts any tunnel where either endpoint type is `vpn_hub` and rejects tunnel relations where neither endpoint is `vpn_hub`.
- `create_link` and `update_link` both call `validate_tunnel_endpoint_hub` before `topology_repo.create_link` / `topology_repo.update_link`, preventing partial persistence on HTTP 400.

## Stable contracts for Slice 2

| Contract | Evidence | Status |
|---|---|---|
| `Node.public_ip` with `ipaddress.ip_address` validator | `backend/models/core.py:23,37-46` | ✅ Landed |
| `Link.medium: Optional[Literal['vpn','sd_wan','satellite']]` | `backend/models/core.py:61` | ✅ Landed |
| `validate_tunnel_endpoint_hub` wired to create/update | `backend/services/link_service.py:26-73,76-105` | ✅ Landed |
| `ALLOWED_TUNNEL_MEDIUMS`, `VPN_HUB_LAYER` | `backend/services/link_service.py:10-11` | ✅ Landed |
| `CategoryIconKey` includes four new keys | `frontend/types.ts:18-21` | ✅ Landed |
| `GraphLink.medium?` frontend type | `frontend/types.ts:110-114` | ✅ Landed |

## Material Symbols check

`frontend/utils/categoryIcons.ts` uses fixed symbols: `vpn_key`, `hub`, `satellite_alt`, `vpn_lock`. Google Fonts Material Symbols CSS resolved each icon name independently with HTTP 200 and generated a font-face response, so none appear invented.

## Commit shape summary

```text
2f4ef6f docs(sdd): clarify budget overrun risk in apply-progress
26d31c4 docs(sdd): mark Slice 1 tasks complete in tasks.md
480b895 docs(sdd): apply-progress for Slice 1 (model + catalog primitives)
0aa8ff5 feat(sdd): GREEN model + catalog primitives for VPN/SD-WAN/satellite
f59bc78 test(sdd): RED failing tests for vpn_tunnel/sd_wan/satellite/vpn_hub primitives
```

Confirmed 5 commits on top of `89dba95`: RED, GREEN, apply-progress, tasks-update, risk-clarify. Commits 1-2 form the strict-TDD RED/GREEN pair; commits 3-5 are documentation hygiene.

Diff stat:

```text
13 files changed, 1491 insertions(+), 18 deletions(-)
```

## Slice boundary confirmation

Command:

```text
git diff --stat 89dba95..HEAD -- backend/engines/snmp_worker.py backend/services/tunnel_health.py backend/routers/tunnels.py frontend/utils/tunnelHealthStyles.ts frontend/components/NetworkVisualizer.tsx frontend/components/VisualRelationshipEditor.tsx frontend/components/MonitoringConsole.tsx
```

Output:

```text
BEGIN_SLICE_BOUNDARY_DIFF
END_SLICE_BOUNDARY_DIFF
```

The Slice 2/3 territory files are empty in the diff.

## Budget overrun acknowledgment

Slice 1 exceeded the 400-line forecast (~1491 insertions / 18 deletions, ~1500 changed lines vs. 400-line review budget). The orchestrator already decided to use `size:exception`; this is acknowledged as a PR-review risk and is **not** a verification failure because the slice boundary is clean and Slice 1 behavior/contracts pass.

## Findings

| Severity | Area | Finding | Mitigation |
|---|---|---|---|
| SUGGESTION | Backend test environment | The literal system command `python -m pytest` fails in this worktree because `/usr/bin/python` has no `pytest`; verification needed a temp uv venv outside the repo. | Document/standardize a backend test runner wrapper or checked-in environment bootstrap for future verifiers. |
| SUGGESTION | API-level public_ip proof | Existing passing coverage verifies model/service/repository persistence and validation, but not an explicit `/api/nodes` read round-trip for top-level `public_ip`. | Add a router-level `/api/nodes` public_ip round-trip test in a follow-up hardening task if the product requires top-level API shape rather than metadata exposure. |

## Verdict

**PASS** — Slice 1 satisfies the Slice 1 spec and stable-contract requirements. Backend touched tests and the full frontend suite passed on fresh execution; Slice 2 and Slice 3 files were not modified.
