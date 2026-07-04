# Design: Tunnel Health Normalization

## Technical Approach

Add a backend-only tunnel health slice that reads existing CI-to-CI relationships with `medium in ['vpn','sd_wan','satellite']`, normalizes authority samples in a pure service, persists latest scalar health fields on the existing relationship, and exposes a scoped read endpoint. Slice 1 contracts stay intact. ICMP/public-IP data is context only and never drives normalized status.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Link identity | Use deterministic unpadded base64url JSON for `{source, relationship, target, medium}`. JSON MUST use canonical key order and compact separators. Decode MUST reject padding requirement ambiguity, decoded payloads over 512 bytes, unknown fields, missing fields, invalid medium, and invalid relationship. | Neo4j internal id; required `Link.id`; hash-only id. | Composite identity is stable and reversible, but only safe if canonical and strictly bounded. |
| Relationship whitelist | Before any dynamic Cypher, pass decoded `relationship` through existing `validate_ci_relationship_type()` / `_validate_relationship()` and use only the returned whitelisted value. | Trust decoded JSON; regex-only validation. | Existing `topology_repo.py` and `services.relationship_types` already centralize injection prevention; reusing them avoids a parallel allowlist. |
| Persistence shape | Store latest health as scalar relationship properties: `tunnel_health_status`, `tunnel_authority_state`, `tunnel_authority_source`, `tunnel_icmp_available`, `tunnel_icmp_latency_ms`, `tunnel_icmp_error`, `tunnel_observed_at`. | Nested map on relationship; separate `TunnelHealth` node; Timescale history. | Neo4j relationship properties must remain scalar/array; latest-only state is enough for Slice 2 and avoids new history/migration scope. |
| Service boundary | Create `backend/services/tunnel_health.py` with Pydantic/dataclass models and pure `normalize_tunnel_health()`. | Embed logic in router or SNMP worker. | Keeps authority rules unit-testable and prevents coupling to metric/event/CI status writers. |
| API behavior | Create authenticated `GET /api/tunnels/{link_id}/health`; invalid id => 400, missing/non-tunnel/inaccessible link => 404. Repository lookup MUST apply `current_user.role` and `allowed_locations` with the existing link scoping rule: non-admin users can read only links where at least one endpoint is in scope. | Query params; reuse `/links`. | Dedicated endpoint keeps link payloads unchanged and prevents client-side-only scoping. |

## Data Flow

    Authenticated client ─GET /api/tunnels/{link_id}/health→ routers/tunnels.py
       └─ tunnel_health.decode_link_id() ── validate relationship whitelist
          └─ topology_repo scoped exact CI-[rel {medium}]->CI read/latest fields

Sample persistence uses the same service/repository helper, but Slice 2 does not add a background poller.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/services/tunnel_health.py` | Create | Pure models, link id encode/decode, authority normalization, ICMP context shaping. |
| `backend/repositories/topology_repo.py` | Modify | Add eligible tunnel lookup, latest-health read/write helpers, exact relationship matching, whitelist validation, and location-scoped reads. |
| `backend/routers/tunnels.py` | Create | Authenticated read endpoint with 400/404 behavior and response model. |
| `backend/main.py` | Modify | Import/register `tunnels.router` with `/api` prefix. |
| `backend/tests/test_tunnel_health.py` | Create | Unit tests for authority and ICMP semantics. |
| `backend/tests/test_topology_tunnel_health.py` | Create | Repository query/property/isolation tests using mock Neo4j driver. |
| `backend/tests/test_routers_tunnels.py` | Create | FastAPI endpoint tests. |

## Interfaces / Contracts

```python
TunnelStatus = Literal["UP", "DOWN", "UNKNOWN"]
AuthorityState = Literal["UP", "DOWN"] | None

class TunnelHealthResponse(BaseModel):
    link_id: str
    source: str
    target: str
    relationship: str
    medium: Literal["vpn", "sd_wan", "satellite"]
    status: TunnelStatus
    authority: AuthorityContext
    icmp: IcmpContext
    observed_at: str | None

class AuthorityContext(BaseModel):
    state: Literal["UP", "DOWN"] | None
    source: str | None
    observed_at: str | None
    reason: Literal["sample", "no_sample"]

class IcmpContext(BaseModel):
    available: bool
    latency_ms: float | None
    error: str | None
    reason: Literal["sample", "missing_public_ip", "no_sample", "failed"]
```

Normalization: `authority.state == 'UP' -> UP`; `DOWN -> DOWN`; `None -> UNKNOWN`. Missing `public_ip` MUST return `icmp.available=false`, `latency_ms=null`, `reason='missing_public_ip'`; no sample MUST return deterministic `UNKNOWN`/`no_sample` fields.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Authority rules, deterministic response fields, missing authority, failed ICMP, missing `public_ip`, canonical link id, size/field/relationship validation. | Write failing tests first in `test_tunnel_health.py`; no DB. |
| Repository | Eligible medium filtering, scoped exact match, relationship whitelist before Cypher, scalar field writes, no `HAS_METRIC`, `Event`, `n.status`, or `r.status` mutation. | Mock Neo4j driver and assert Cypher/params. |
| API | 200 eligible link, 400 malformed/oversized/unknown-field `link_id`, 404 non-tunnel/not found/inaccessible, missing `public_ip` and no-sample bodies preserved. | TestClient with auth dependency overrides and mocked service/repo. |
| E2E | Not required for backend-only Slice 2. | Automated backend tests are sufficient. |

Strict TDD: add tests before implementation, then implement minimal service/repo/router changes. Expected review size is medium and should stay under the 800-line budget if kept to one backend slice.

## Migration / Rollout

No required data migration. Latest health properties are written lazily when samples are saved. Existing relationships without samples read as `UNKNOWN` with no-sample context.

## Open Questions

- [ ] None.
