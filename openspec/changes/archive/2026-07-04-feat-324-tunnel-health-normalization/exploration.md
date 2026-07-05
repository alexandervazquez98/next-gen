## Exploration: feat-324-tunnel-health-normalization

### Current State
Slice 1 is present in this worktree. Canonical OpenSpec specs include `vpn-tunnel-relations` and `category-technology-icons`; the Slice 1 archive is also present. The backend model already supports `Node.public_ip`, `Link.medium` values `vpn|sd_wan|satellite`, `vpn_hub` endpoint validation, and link/graph read exposure without changing node status or event fields.

Tunnel health does not exist yet as a first-class backend capability. There is no `backend/services/tunnel_health.py`, no `backend/routers/tunnels.py`, and no tunnel-specific tests. Existing collection paths are node-metric oriented: `backend/engines/snmp_worker.py` polls `(CI)-[:HAS_METRIC]->(MetricDef)` and writes metrics/events/status, while `backend/polling/snmp_executor.py` normalizes leased SNMP/ICMP task results. ICMP helpers already expose structured `PingMeasurement`, latency parsing, sidecar telemetry, and threshold evaluation that can be reused for tunnel liveness context.

### Affected Areas
- `openspec/specs/vpn-tunnel-relations/spec.md` — Source-of-truth Slice 1 model contract that Slice 2 should consume, not modify destructively.
- `openspec/changes/archive/2026-06-27-feat-324-vpn-sdwan-satellite-link-simulation-slice-1/` — Archived prior plan contains deferred Slice 2 design/tasks that are useful input but must be adapted to the confirmed product decisions.
- `backend/models/core.py` — `Node.public_ip` and `Link.medium` primitives already exist and define valid tunnel inputs.
- `backend/services/link_service.py` — Central tunnel medium constants and hub-required validation already exist; likely source for shared medium validation.
- `backend/repositories/topology_repo.py` — Current repository reads/writes `medium`; Slice 2 needs read/query helpers for tunnel links and a relationship health sample writer/reader.
- `backend/engines/snmp_worker.py` — Existing engine has SNMP and ICMP fetch helpers, but its main loop is metric/event/status oriented; tunnel polling must remain isolated from `HAS_METRIC`, `Event`, and CI status writes.
- `backend/polling/icmp_measurements.py` — Reusable structured ping and threshold utilities for liveness/RTT context.
- `backend/main.py` — Router registry location for a future `/api/tunnels/{link_id}/health` endpoint.
- `backend/tests/test_topology_relationships.py` and `backend/tests/test_routers_links.py` — Existing Slice 1 tests prove tunnel primitives; Slice 2 should add focused backend tests for rollup, isolation, repository samples, and endpoint behavior.

### Approaches
1. **Isolated tunnel health service + relationship sample endpoint** — Add pure rollup and sampling helpers in a new service, add repository functions for `medium` relationships, store latest normalized health fields on the relationship, and expose a read-only tunnel health endpoint.
   - Pros: Preserves existing metric/event pipelines; aligns with confirmed rule that SNMP/CLI authority controls UP/DOWN; small backend-only Slice 2 surface; testable with pure unit tests and mocked repository/router tests.
   - Cons: Relationship latest-state storage is not historical; requires careful link identity/query design because existing links are source/target/type oriented and do not expose a stable separate link id.
   - Effort: Medium

2. **Extend existing metric/ICMP pipeline with tunnel MetricDefs** — Model tunnel authority and ICMP context as additional metric definitions tied to CIs or relationships and reuse the existing event writer pipeline.
   - Pros: Reuses existing polling/storage/event infrastructure.
   - Cons: Violates Slice 2 isolation intent; risks false CI/node events and CI status changes; makes ICMP authority creep more likely; expands scope into event semantics rather than normalization first.
   - Effort: High

### Recommendation
Use the isolated tunnel health service + relationship sample endpoint. The proposal should scope Slice 2 to backend normalization only: query existing `medium` links, resolve endpoint `public_ip`, normalize authority samples from existing/simulable SNMP/CLI signals, add ICMP RTT/liveness context only when available, store latest health on the relationship, and expose a read endpoint. The rollup contract should be explicit and authority-driven: SNMP/CLI `DOWN` returns `DOWN`, SNMP/CLI `UP` remains `UP` even when ICMP context is poor, ICMP failure never returns `DEGRADED` or `DOWN`, and missing `public_ip` returns `UNKNOWN`/unavailable ICMP context rather than degraded.

### Risks
- Existing links do not expose a dedicated stable `link_id`; endpoint design must choose and document a deterministic identifier or use source/target/relationship lookup semantics.
- `snmp_worker.py` is large and event-sensitive; adding tunnel polling inline risks accidental metric/event/status side effects unless helpers are isolated and tests prove no `HAS_METRIC`/`Event`/CI status writes.
- Archived Slice 2 notes mention vendor registry/OID placeholders; confirmed scope says no Cisco-specific or multi-vendor adapters, so proposal/spec must keep adapter work out of scope and rely on existing or simulable signals.
- Missing `public_ip` behavior must stay `UNKNOWN`/unavailable context, not `DEGRADED`; this needs direct tests because it differs from common liveness assumptions.

### Ready for Proposal
Yes — proceed to `sdd-propose` for Slice 2 only. Tell the user the worktree already contains Slice 1 primitives and archived guidance; the next artifact should define a backend-only change for tunnel health normalization, latest-health persistence/read endpoint, and rollup tests, explicitly excluding frontend visualization and vendor-specific adapters.
