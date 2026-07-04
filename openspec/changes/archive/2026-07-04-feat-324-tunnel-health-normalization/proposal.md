# Proposal: Tunnel Health Normalization

## Intent

Normalize backend tunnel health for VPN, SD-WAN, and satellite links so operators can read latest tunnel state through an API without changing existing node status, metric, event, or frontend behavior. SNMP/CLI authority exclusively drives normalized status in Slice 2: authority `UP` yields `UP`, authority `DOWN` yields `DOWN`, and missing authority yields `UNKNOWN`. ICMP/public-IP checks only add liveness and RTT context and MUST NOT change normalized status to `DEGRADED` or `DOWN`.

## Scope

### In Scope
- Backend-only tunnel health normalization and rollup for Slice 2: authority `UP` => `UP`, authority `DOWN` => `DOWN`, missing authority => `UNKNOWN`; ICMP/public-IP context MUST NOT produce `DEGRADED` or `DOWN`.
- Latest-health persistence/read behavior for existing tunnel relations using `medium: vpn|sd_wan|satellite`.
- Read endpoint such as `GET /api/tunnels/{link_id}/health` backed by existing or simulable SNMP/CLI/ICMP signals.
- Tests for authority rules, missing `public_ip`, latest read behavior, and pipeline isolation.

### Out of Scope
- Frontend visual states, Monitoring Console filter, tooltips, or rendering changes.
- Cisco-specific, vendor-complete, or multi-vendor OID/CLI adapters.
- Changes to Slice 1 contracts: `vpn_hub`, `public_ip`, `Link.medium`, and hub-required tunnel validation.
- Mutating node metric, event, or CI status pipelines for tunnel health.

## Capabilities

### New Capabilities
- `tunnel-monitoring`: Backend tunnel health normalization, latest-health storage/read API, and SNMP/CLI-authoritative rollup with ICMP context.

### Modified Capabilities
- `vpn-tunnel-relations`: Preserve Slice 1 tunnel relation contracts while allowing tunnel-health consumers to identify eligible tunnel links safely.

## Approach

Add an isolated tunnel health service and repository helpers. Query existing tunnel-medium relationships, resolve endpoint `public_ip`, normalize SNMP/CLI authority samples, enrich with ICMP RTT/liveness only when available, and persist the latest health on the relationship or adjacent health record. Missing authority yields normalized `UNKNOWN`; missing `public_ip` yields unavailable ICMP context without changing the authority-driven normalized status. Avoid coupling to `HAS_METRIC`, `Event`, or CI status writes.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/services/tunnel_health.py` | New | Rollup and normalization rules. |
| `backend/repositories/topology_repo.py` | Modified | Tunnel link lookup and latest-health read/write. |
| `backend/routers/tunnels.py`, `backend/main.py` | New/Modified | Register tunnel health read endpoint. |
| `backend/polling/icmp_measurements.py` | Modified | Reuse ICMP measurement context only. |
| `backend/tests/` | Modified | Backend tests for rollup, endpoint, persistence, isolation. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Links may lack stable dedicated `link_id` | High | Specify deterministic relationship identity or source/target/type/medium lookup before endpoint specs. |
| Accidental metric/event/status mutation | Med | Keep service isolated and test no pipeline side effects. |
| ICMP semantics drift into authority | Med | Test ICMP never returns `DEGRADED` or `DOWN`; missing `public_ip` only affects ICMP context. |

## Rollback Plan

Remove the tunnel router/service/repository health helpers and latest-health fields. Existing Slice 1 tunnel relations remain valid because no `public_ip`, `medium`, or hub-validation contract is changed.

## Dependencies

- Slice 1 tunnel primitives already merged via PR #339.
- Existing ICMP measurement utilities and simulable SNMP/CLI authority samples.

## Success Criteria

- [ ] Backend returns latest normalized tunnel health for eligible tunnel links.
- [ ] SNMP/CLI authority controls normalized status: `UP`, `DOWN`, or `UNKNOWN` when missing.
- [ ] ICMP/public-IP liveness and RTT are context only and never produce `DEGRADED` or `DOWN`.
- [ ] Missing `public_ip` reports unavailable ICMP context, not degradation.
- [ ] Tests prove existing metric/event/CI status pipelines remain isolated.
