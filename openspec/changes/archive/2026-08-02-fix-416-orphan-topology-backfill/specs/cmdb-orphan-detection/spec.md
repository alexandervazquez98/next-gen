# Delta for CMDB Orphan Detection (first appearance under `fix-416-orphan-topology-backfill`)

> **Note**: This capability does not exist in `openspec/specs/` prior to this change. The canonical source of truth is `openspec/specs/cmdb-orphan-detection/spec.md`; this delta is the change-scoped view that downstream `sdd-design` and `sdd-tasks` consume. All REQ/SCN IDs mirror the canonical spec. Operator-runbook and changelog enforcement items are change-scoped additions (REQ-100..102 / SCN-100..101) that apply only to this rollout.

## ADDED Requirements

### Requirement: REQ-001 — Scope Restricted to APs in This Slice

The CLI SHALL accept `--scope ap` and SHALL reject any other value with a non-zero exit and a single-line stderr error shaped `error: invalid --scope <value>; allowed: ap`. When `--scope` is omitted the CLI SHALL default to `ap`. No Neo4j query SHALL be issued before scope validation succeeds.

#### Scenario: `--scope ap` accepted

- GIVEN the CLI is invoked with `--scope ap`
- WHEN the run executes
- THEN scope validation passes and the Neo4j query proceeds
- AND the audit log records `scope=ap`.

#### Scenario: `--scope switch` rejected before any query

- GIVEN the fake session is wired but MUST NOT be called
- WHEN the CLI is invoked with `--scope switch`
- THEN exit code is non-zero, stderr contains `error: invalid --scope switch; allowed: ap`, and no `query_hash` is emitted.

### Requirement: REQ-002 — Default Upstream Edges and `CONNECTS_TO` Exclusion

The default `--relationship-types` SHALL be `DEPENDS_ON,HOSTED_ON` per `correlation-topology-guide.md`. `CONNECTS_TO` SHALL be excluded from the default. `--relationship-types` SHALL be an explicit allowlist — values outside `{DEPENDS_ON, HOSTED_ON, MANAGES, RUNS_ON}` SHALL be rejected; raw Cypher fragments SHALL never be accepted.

#### Scenario: Default rels

- GIVEN the CLI is invoked with no `--relationship-types`
- WHEN the run executes
- THEN the audit log records `rels=DEPENDS_ON,HOSTED_ON`
- AND only those edge types are used to determine parentage.

#### Scenario: Allowlist rejects raw Cypher

- GIVEN `--relationship-types "MATCH (n) DELETE n"`
- WHEN the CLI parses the argument
- THEN the run exits non-zero before any Neo4j session is opened.

### Requirement: REQ-003 — JSON Output Schema

The CLI SHALL emit a single JSON object with exactly these top-level keys: `as_of` (ISO 8601 UTC with trailing `Z`), `scope` (string), `relationship_types` (list of strings), `orphan_count` (non-negative integer), `ci_ids` (list of opaque CI ID strings). `orphan_count` SHALL equal `len(ci_ids)`. No additional top-level keys SHALL appear.

#### Scenario: Successful run schema match

- GIVEN a successful run
- WHEN the JSON output is parsed
- THEN it matches the schema above exactly.

#### Scenario: Empty graph edge case

- GIVEN the fake session returns zero orphan APs
- WHEN the run executes
- THEN `orphan_count: 0` and `ci_ids: []` and the JSON still matches the schema.

### Requirement: REQ-004 — Enrichment Constraint — Opaque CI IDs Only

Stdout and stderr SHALL contain only opaque CI ID strings (UUID-shaped or `ci-test-ap-orphan-NNN` placeholder form). The CLI SHALL NOT emit, log, or include CI names, IPs, sites, locations, relationship attributes, or any other CI metadata. Non-opaque values returned by Neo4j SHALL be stripped from `ci_ids`.

#### Scenario: Pure ID output

- GIVEN any successful run
- WHEN stdout and stderr are scanned
- THEN they contain only `ci_ids` plus audit metadata.

#### Scenario: Extra property stripped

- GIVEN a CI record with `id` plus an extra `name` property
- WHEN the CLI composes the output
- THEN the extra property is dropped and only the `id` appears in `ci_ids`.

### Requirement: REQ-005 — Audit Log Shape on stderr

A single stderr line SHALL be emitted per run with key=value pairs in order: `ts`, `query_hash` (sha256 prefix, ≥ 8 hex chars), `scope`, `rels` (comma-separated), `orphan_count`, `exit`. The line SHALL NOT include any CI ID, name, or credential. Stdout SHALL remain pure JSON.

#### Scenario: Single audit line emitted

- GIVEN any run (success or failure)
- WHEN stderr is captured
- THEN exactly one line matching the schema is emitted, in the specified order.

#### Scenario: Audit line never contains CI IDs

- GIVEN a run returning 50 orphan APs
- WHEN stderr is captured
- THEN the audit line contains `orphan_count=50` and zero CI ID substrings.

### Requirement: REQ-006 — Output Routing and Path Safety

When `--output <path>` is provided, the CLI SHALL write the JSON object to that file and stdout SHALL be empty. When omitted (or set to `-`), the CLI SHALL emit the JSON object to stdout. Paths that escape the working tree via `..` traversal SHALL be rejected with a non-zero exit and stderr error.

#### Scenario: File output

- GIVEN `--output /tmp/orphans.json`
- WHEN the run executes
- THEN the file exists with valid JSON matching REQ-003 and stdout is empty.

#### Scenario: Path traversal rejected

- GIVEN `--output ../escape.json`
- WHEN the CLI validates the path
- THEN the run exits non-zero with a stderr error and no file is written.

### Requirement: REQ-007 — Read-Only Invariant

The CLI SHALL open only read Neo4j sessions. The script SHALL fail-fast at import time if any `topology_repo` write helper is referenced. No write transaction SHALL be issued under any code path.

#### Scenario: Write helper import fails fast

- GIVEN the script imports `topology_repo` write helpers
- WHEN Python resolves the imports
- THEN the process exits non-zero before any CLI argument parsing.

#### Scenario: Driver write call fails fast

- GIVEN the running code attempts `session.execute_write(...)`
- WHEN the call site executes
- THEN the process exits non-zero.

### Requirement: REQ-008 — Neo4j URI Required, Credentials Never Logged

`--neo4j-uri` SHALL be required at runtime; the CLI SHALL also honor `$NEO4J_URI` as fallback. Missing both SHALL exit non-zero with stderr `error: --neo4j-uri (or $NEO4J_URI) required`. Credentials SHALL NEVER appear in stdout, stderr, or the audit log.

#### Scenario: Missing URI exits non-zero

- GIVEN no `--neo4j-uri` and no `$NEO4J_URI`
- WHEN the run starts
- THEN the CLI exits non-zero with a stderr error and no credentials appear anywhere.

#### Scenario: Env fallback honored

- GIVEN `$NEO4J_URI=bolt://fake` is set
- WHEN the run starts without `--neo4j-uri`
- THEN the CLI proceeds using the env value and never logs it.

### Requirement: REQ-009 — `.gitignore` Coverage for `openspec/scripts/output/`

The repository `.gitignore` SHALL contain the entry `openspec/scripts/output/` (with trailing slash preferred). The entry SHALL match the directory and any file within it under `git check-ignore`.

#### Scenario: git check-ignore passes

- GIVEN the repo working tree
- WHEN `git check-ignore openspec/scripts/output/example.json` runs
- THEN the command exits 0 (path is ignored).

### Requirement: REQ-010 — Synthetic Test Fixtures Only

Every automated test SHALL exercise a fake Neo4j driver or mock session. No test SHALL connect to a real Neo4j. Every CI ID in fixtures SHALL match `^ci-test-ap-orphan-\d{3,}$` or be a UUID-shaped opaque string.

#### Scenario: pytest never opens a real Neo4j connection

- GIVEN the test suite
- WHEN it runs under `cd backend && .venv/bin/python -m pytest`
- THEN no network connection to Neo4j is opened and every fixture ID matches the synthetic pattern.

#### Scenario: Real-shape ID rejected by fixture guard

- GIVEN a fixture accidentally introduces a non-synthetic CI ID (e.g. a hostname-shaped string)
- WHEN pytest collects and runs the test
- THEN the test fails with a clear fixture-validation error.

### Requirement: REQ-100 — Operator Runbook Sequence (change-scoped)

The `openspec/scripts/OPERATOR_RUNBOOK.md` (or its inline proposal counterpart) SHALL document the four-step operator sequence from the proposal: (1) export `NEO4J_URI`/user/password from a sealed secret store; (2) invoke the script with `--output /tmp/<utc-timestamp>-orphans.json`; (3) feed the file to internal CMDB tooling (NOT this script — read-only); (4) delete the file after use; never copy into the repo tree.

#### Scenario: Runbook present and accurate

- GIVEN the change is shipped
- WHEN the operator runbook is read
- THEN it documents the four steps and never instructs copying the JSON output into the repo tree.

### Requirement: REQ-101 — `CHANGELOG.md` `[Unreleased]` Entry (change-scoped)

`CHANGELOG.md` SHALL contain an `[Unreleased]` → `### Added` entry naming the new CLI and pointing to `openspec/scripts/cmdb_backfill_orphans.py`. The entry SHALL NOT include any real CI IDs, names, IPs, sites, or locations.

#### Scenario: Changelog entry exists

- GIVEN the change is shipped
- WHEN `CHANGELOG.md` is read
- THEN it has an `[Unreleased]` → `### Added` line referencing the CLI without disclosing customer data.

### Requirement: REQ-102 — Test Suite Executable via Project Pytest (change-scoped)

The synthetic-fixture test suite SHALL be runnable via `cd backend && .venv/bin/python -m pytest` and SHALL pass with no Neo4j dependency installed.

#### Scenario: Pytest green without Neo4j

- GIVEN the repo with the new tests in place and no running Neo4j
- WHEN the operator runs `cd backend && .venv/bin/python -m pytest`
- THEN the suite exits 0 with no skipped tests due to missing Neo4j.

## Scenario Matrix

| ID | Surface | WHEN | THEN |
|---|---|---|---|
| SCN-001 | Default run | WHEN the synthetic graph contains N orphan APs only | THEN `orphan_count == N` and `ci_ids` lists the N synthetic IDs |
| SCN-002 | Wired APs | WHEN APs have `DEPENDS_ON` or `HOSTED_ON` edges | THEN they are excluded |
| SCN-003 | `CONNECTS_TO` only | WHEN APs have only `CONNECTS_TO` edges | THEN they appear as orphans |
| SCN-004 | Custom allowlist | WHEN `--relationship-types HOSTED_ON` | THEN only `HOSTED_ON` parentage counts |
| SCN-005 | File output | WHEN `--output <path>` is provided | THEN the file holds valid JSON and stdout is empty |
| SCN-006 | Stdout purity | WHEN no `--output` flag | THEN stdout is pure JSON |
| SCN-007 | Audit shape | WHEN any run completes | THEN stderr holds exactly one line per REQ-005 |
| SCN-008 | Scope validation | WHEN `--scope` is not `ap` | THEN exit non-zero, no Neo4j query |
| SCN-009 | Missing URI | WHEN `--neo4j-uri` and `$NEO4J_URI` are absent | THEN exit non-zero, no credentials logged |
| SCN-010 | Safety cap | WHEN orphan APs exceed 10,000 | THEN `orphan_count` reflects 10,000 cap and `cap_reached=true` |
| SCN-011 | Schema drift | WHEN Neo4j reports a missing label | THEN exit non-zero with the label name in stderr |
| SCN-012 | `.gitignore` | WHEN the script would write into `openspec/scripts/output/` | THEN git treats the path as ignored |
| SCN-100 | Runbook | WHEN an operator reads the runbook | THEN the four-step sequence is documented and never instructs copying output into the repo tree |
| SCN-101 | Changelog | WHEN `CHANGELOG.md` is read | THEN the `[Unreleased]` → `### Added` entry references the CLI without customer data |

## Out of Scope

- **Auto-write / auto-wiring of relationships** (deferred to P3b). The script is read-only by design.
- **Heuristics** — no name-matching, IP-matching, site-matching, or relationship inference. Pure dry-run detection.
- **Non-AP CI types** — switch, router, server, etc. are out of scope; only `ap` is accepted in this slice.
- **Enrichment beyond opaque CI IDs** — no names, IPs, sites, locations, or relationship attributes in stdout.
- **Modify `topology_repo` writers or `services/snmp_service.py`** — the script reuses read helpers only.
- **Queue/legacy collector parity** — this is offline SDD tooling; it does not run inside the API process.
- **"Explain" mode or per-orphan narrative** — flat list of opaque IDs only.
- **Real customer data** — CI IDs are opaque UUIDs; examples use placeholders (`ci-example-uuid-NNN`, `ci-test-ap-orphan-NNN`). Names, IPs, sites, locations, and credentials never appear in this delta, in any test fixture, in any example, or in any captured output.
- **`CONNECTS_TO` parentage** — explicitly excluded per `correlation-topology-guide.md`.

## Open Questions

- Whether the safety cap should be configurable via `--max-orphans` (default 10,000). Current decision: hard-coded constant for P3a; flag-gating deferred until an operator needs it.
- Whether `MANAGES` and `RUNS_ON` belong in the default allowlist alongside `DEPENDS_ON,HOSTED_ON`. Current decision: they are accepted by the allowlist but not enabled by default; an operator can opt in via `--relationship-types`.
