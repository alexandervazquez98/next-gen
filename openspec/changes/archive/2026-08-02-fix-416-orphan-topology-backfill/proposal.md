# Proposal: CMDB Orphan Topology Backfill (P3a of fix #416)

## Intent

P0 write-time correlation (`event-write-time-correlation`) suppresses N+1 events only when a parent CI exists in Neo4j. Issue #416 documents ~50 Access Points with no registered parent, including the worst-case 168x amplification on one CI referenced in that issue. P3a ships an **offline, read-only** discovery tool that surfaces those orphan APs so an operator can manually wire them. **No auto-write, no heuristics, no enrichment — discovery only.**

## Scope

### In Scope
- `openspec/scripts/cmdb_backfill_orphans.py`: read-only CLI finding APs with no upstream under `DEPENDS_ON|HOSTED_ON`.
- Strict-TDD tests using **synthetic CI IDs only** (`ci-test-ap-orphan-NNN`).
- `.gitignore` entry for `openspec/scripts/output/`.
- Operator runbook + `CHANGELOG.md` `[Unreleased]` entry.

### Out of Scope (locked decisions)
- Write mode / auto-wiring of relationships (deferred P3b).
- Naming, IP, or site heuristics.
- Non-AP CI types.
- Modifying `topology_repo` writers or `services/snmp_service.py`.
- Queue/legacy collector parity.
- "Explain" mode or per-orphan enrichment beyond the opaque ID.

## Capabilities

### New Capabilities
- `cmdb-orphan-detection`: offline, read-only discovery of CIs (APs in this slice) lacking an upstream relationship under the configured edge types. Returns opaque CI IDs only.

### Modified Capabilities
- None.

## Approach

Single Python CLI in `openspec/scripts/`. Reuses `backend.repositories.topology_repo` read helpers (`build_open_parent_index`, `get_topology_relations`) as-is. Read-only Neo4j session, never writes.

| Flag | Default | Purpose |
|---|---|---|
| `--neo4j-uri` | `$NEO4J_URI` | Bolt URI; required at runtime, never committed. |
| `--scope` | `ap` | `ap` only in this slice. |
| `--relationship-types` | `DEPENDS_ON,HOSTED_ON` | Upstream edges. `CONNECTS_TO` excluded (no parentage semantics per `correlation-topology-guide.md`). |
| `--format` | `json` | JSON only. |
| `--output` | `-` (stdout) | File path; stdout otherwise. |

### Output schema (stdout / `--output`)
```json
{
  "as_of": "2026-08-01T12:34:56Z",
  "scope": "ap",
  "relationship_types": ["DEPENDS_ON", "HOSTED_ON"],
  "orphan_count": 2,
  "ci_ids": ["ci-example-uuid-001", "ci-example-uuid-002"]
}
```

### Stderr audit line (per run)
```
ts=2026-08-01T12:34:56Z query_hash=<sha256-8> scope=ap rels=DEPENDS_ON,HOSTED_ON orphan_count=2 exit=0
```
Audit metadata only — never CI IDs, never names, never customer fields.

### Operator runbook
1. Export `NEO4J_URI`/user/password from a sealed secret store (never committed).
2. `python openspec/scripts/cmdb_backfill_orphans.py --output /tmp/$(date -u +%Y%m%dT%H%M%SZ)-orphans.json`.
3. Feed the file to internal CMDB tooling (NOT this script — read-only).
4. Delete the file after use; never copy into the repo tree.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `openspec/scripts/cmdb_backfill_orphans.py` | New | Read-only orphan discovery CLI. |
| `openspec/scripts/__init__.py` | New | Package marker so tests run via `pytest` from `backend/`. |
| `openspec/scripts/tests/test_cmdb_backfill_orphans.py` | New | Strict-TDD synthetic-fixture suite. |
| `.gitignore` | Modified | Adds `openspec/scripts/output/`. |
| `CHANGELOG.md` | Modified | `[Unreleased]` entry under `### Added`. |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| False positives (CI genuinely has no parent by design) | Med | Operator confirms in internal tooling before any wire. No auto-write path exists. |
| CI ID leakage into committed files | Low | Stderr audit only; stdout = opaque UUIDs; tests + fixtures use synthetic IDs; `openspec/scripts/output/` git-ignored; no real IDs in docs or examples. |
| Neo4j schema drift (label changes) | Low | Single relationship-type allowlist constant; fail-fast on missing label; test asserts error shape. |
| Slow query on large graphs | Low | Indexed `(:CI)` MATCH; no full scan; LIMIT 10000 safety cap. |
| Path confusion with `backend/scripts/` audit convention | Low | `openspec/scripts/` chosen because this is offline SDD-tooling shipped with the change, not a backend runtime tool. |

## Rollback Plan
Delete `openspec/scripts/cmdb_backfill_orphans.py`, its test, and the `.gitignore` line. **No DB migration** — the script never writes to Neo4j.

## Success Criteria

- [ ] Synthetic graph with N orphan APs + M wired APs → script reports exactly N IDs, all synthetic.
- [ ] Stderr audit line contains `ts`, `query_hash`, `scope`, `rels`, `orphan_count`, `exit`.
- [ ] `--output <path>` writes JSON; default emits to stdout; pure JSON with opaque IDs only.
- [ ] **Zero** real customer-identifying data (names, IPs, sites, locations) in output, fixtures, tests, examples, or proposal text.
- [ ] `openspec/scripts/output/` git-ignored; repo contains zero committed orphan reports.
- [ ] `CONNECTS_TO` excluded by default; `--relationship-types` override is allowlisted, never raw Cypher.
- [ ] All tests pass under `cd backend && .venv/bin/python -m pytest`.

## Dependencies
- Read-only Neo4j credentials (operator-managed, never committed).
- `backend.repositories.topology_repo` read helpers — used as-is.

## Linked Artifacts
- Source issue: `alexandervazquez98/next-gen#416`.
- Prior art: `openspec/changes/archive/2026-08-01-fix-416-event-amplification-p2/` (P2 deferred this slice).
- Companion capability: `openspec/specs/event-write-time-correlation/spec.md`.

## Security Constraint (reaffirmed)

No real customer names, IPs, sites, locations, or any non-opaque CI metadata appear in this proposal, in any committed file, in any test fixture, in any documentation example, or in any captured output. CI IDs are opaque UUIDs; examples use placeholders (`ci-example-uuid-NNN`). The audit trail lives in stderr and contains only `ts`, query hash, scope, relationship types, count, and exit code.