# Tasks: Tunnel Health Normalization

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 520-680 |
| 800-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single backend Slice 2 PR |
| Delivery strategy | ask-always |
| Chain strategy | N/A unless user chooses to split further |

Decision needed before apply: Yes — estimate exceeds the 400-line downstream guard; user must choose single PR with size exception or split further before apply.
Chained PRs recommended: No
Chain strategy: N/A unless split further
800-line budget risk: Low
400-line budget risk: Medium

### Suggested Work Units / Commit Guidance

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Pure tunnel-health service and ID validation | Single PR | Commit tests with service code. |
| 2 | Repository latest-health read/write and scoping | Single PR | Commit repository tests with Cypher helpers. |
| 3 | Authenticated API endpoint and registration | Single PR | Commit API tests with router code. |

Keep commits behavior-based, not file-type based. Each commit must include its RED test, GREEN implementation, and related refactor.

## Phase 1: RED Service Tests

- [x] 1.1 Create `backend/tests/test_tunnel_health.py` cases for authority `UP`, `DOWN`, missing authority, ICMP failure, missing `public_ip`, and no ICMP sample.
- [x] 1.2 Add canonical `link_id` tests for unpadded base64url JSON key order, compact separators, unknown fields, missing fields, invalid medium, oversize >512 bytes, and unsafe relationship rejection.

## Phase 2: GREEN Service Implementation

- [x] 2.1 Create `backend/services/tunnel_health.py` models, `encode_link_id()`, `decode_link_id()`, and `normalize_tunnel_health()`.
- [x] 2.2 Ensure ICMP never returns normalized `DEGRADED` or `DOWN`; status domain is only `UP`, `DOWN`, `UNKNOWN`.

## Phase 3: RED Repository Tests

- [x] 3.1 Create `backend/tests/test_topology_tunnel_health.py` for eligible `vpn|sd_wan|satellite` exact-link lookup and non-tunnel exclusion.
- [x] 3.2 Test relationship whitelist validation occurs before dynamic Cypher and inaccessible non-admin links return no row.
- [x] 3.3 Test latest scalar relationship properties are read/written and no `HAS_METRIC`, `Event`, `n.status`, or `r.status` mutation appears in Cypher.

## Phase 4: GREEN Repository Implementation

- [x] 4.1 Update `backend/repositories/topology_repo.py` with scoped tunnel lookup using decoded identity and existing relationship validators.
- [x] 4.2 Add latest-health read/write helpers with scalar properties from the design contract.

## Phase 5: RED API Tests

- [x] 5.1 Create `backend/tests/test_routers_tunnels.py` for authenticated 200, malformed/oversized/unknown-field 400, and missing/non-tunnel/inaccessible 404.
- [x] 5.2 Test deterministic response bodies for authority sample, no sample, missing `public_ip`, and ICMP failure states.

## Phase 6: GREEN API Wiring

- [x] 6.1 Create `backend/routers/tunnels.py` with `GET /api/tunnels/{link_id}/health`, auth dependency, scoped repository call, and 400/404 mapping.
- [x] 6.2 Register `tunnels.router` in `backend/main.py` under `/api` without frontend, vendor-adapter, poller, metric, event, or CI-status changes.

## Phase 7: REFACTOR / Verify

- [x] 7.1 Refactor duplicated fixtures/helpers only after tests pass; keep public response shape deterministic.
- [x] 7.2 Run `backend/.venv/bin/python -m pytest backend/tests/test_tunnel_health.py backend/tests/test_topology_tunnel_health.py backend/tests/test_routers_tunnels.py` from repo root.
