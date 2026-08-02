# Spec: CMDB Orphan Detection

## Purpose

Define a read-only, offline CLI (`openspec/scripts/cmdb_backfill_orphans.py`) that surfaces Configuration Items (CIs) lacking an upstream parent relationship under the configured edge types so an operator can manually wire them in internal CMDB tooling. This is the P3a slice of fix #416: P0 (`event-write-time-correlation`) and P2 (`event-root-affected-exposure`) already suppress N+1 events when the parent is wired; this tool discovers the cases where the parent is missing entirely. No auto-write, no heuristics, no enrichment beyond opaque CI IDs.

The capability is intentionally non-runtime: the script ships under `openspec/scripts/` rather than `backend/scripts/` because it is offline SDD tooling delivered with this change, never imported by the running API or collector. The CLI reads Neo4j only and writes JSON only — never a write transaction, never a credential, never a customer field.

## Requirements

### REQ-001: Scope Restricted to APs in This Slice

The CLI SHALL accept `--scope ap` and SHALL reject any other value with a non-zero exit and a single-line stderr error shaped `error: invalid --scope <value>; allowed: ap`. When `--scope` is omitted the CLI SHALL default to `ap`. No Neo4j query SHALL be issued before scope validation succeeds.

#### Acceptance

- GIVEN the CLI is invoked with `--scope ap`
- WHEN the run executes
- THEN scope validation passes and the Neo4j query proceeds
- AND the audit log records `scope=ap`.

#### Edge cases

- `--scope` omitted → defaults to `ap`.
- `--scope AP` (case mismatch) → rejected with the standard error shape.
- `--scope switch` → rejected, no Neo4j query, no `query_hash` emitted.

### REQ-002: Default Upstream Edges and `CONNECTS_TO` Exclusion

The default `--relationship-types` SHALL be `DEPENDS_ON,HOSTED_ON` per `correlation-topology-guide.md`. `CONNECTS_TO` SHALL be excluded from the default. `--relationship-types` SHALL be an explicit allowlist — values outside `{DEPENDS_ON, HOSTED_ON, MANAGES, RUNS_ON}` SHALL be rejected; raw Cypher fragments SHALL never be accepted.

#### Acceptance

- GIVEN the CLI is invoked with no `--relationship-types`
- WHEN the run executes
- THEN the audit log records `rels=DEPENDS_ON,HOSTED_ON`
- AND only those edge types are used to determine parentage.

#### Edge cases

- `--relationship-types CONNECTS_TO` → rejected (allowlist).
- `--relationship-types "MATCH (n) DELETE n"` → rejected (raw Cypher).
- Duplicate values → silently deduped.

### REQ-003: JSON Output Schema

The CLI SHALL emit a single JSON object with exactly these top-level keys: `as_of` (ISO 8601 UTC string with trailing `Z`), `scope` (string), `relationship_types` (list of strings), `orphan_count` (non-negative integer), `ci_ids` (list of opaque CI ID strings). `orphan_count` SHALL equal `len(ci_ids)`. No additional top-level keys SHALL appear.

#### Acceptance

- GIVEN a successful run
- WHEN the JSON output is parsed
- THEN it matches the schema above exactly.

#### Edge cases

- Empty graph → `orphan_count: 0`, `ci_ids: []`.
- Duplicate CI IDs in the upstream view → deduped before output.
- `as_of` always UTC with trailing `Z`.

### REQ-004: Enrichment Constraint — Opaque CI IDs Only

Stdout and stderr SHALL contain only opaque CI ID strings (UUID-shaped or `ci-test-ap-orphan-NNN` placeholder form). The CLI SHALL NOT emit, log, or include CI names, IPs, sites, locations, relationship attributes, or any other CI metadata. Non-opaque values returned by Neo4j SHALL be stripped from `ci_ids`.

#### Acceptance

- GIVEN any successful run
- WHEN stdout and stderr are scanned
- THEN they contain only `ci_ids` plus audit metadata.

#### Edge cases

- CI record carries extra property (e.g. `name`, `ip`) → property dropped from output.
- CI record `id` field absent → that CI is skipped (not surfaced as orphan).

### REQ-005: Audit Log Shape on stderr

A single stderr line SHALL be emitted per run with key=value pairs in order: `ts` (ISO 8601 UTC), `query_hash` (sha256 prefix, ≥ 8 hex chars), `scope`, `rels` (comma-separated), `orphan_count`, `exit` (integer). The line SHALL NOT include any CI ID, name, or credential. Stdout SHALL remain pure JSON — the audit line SHALL NEVER appear on stdout.

#### Acceptance

- GIVEN any run (success or failure)
- WHEN stderr is captured
- THEN exactly one line matching the schema is emitted, in the specified order.

#### Edge cases

- Exit non-zero → `exit` reflects the failure code; line still emitted.
- Two runs with identical input → distinct `query_hash` per run only if timestamp differs; identical timestamp + input → identical hash (acceptable, ids are never hashed in).

### REQ-006: Output Routing and Path Safety

When `--output <path>` is provided, the CLI SHALL write the JSON object to that file and stdout SHALL be empty. When omitted (or set to `-`), the CLI SHALL emit the JSON object to stdout. Paths that escape the working tree via `..` traversal SHALL be rejected with a non-zero exit and stderr error.

#### Acceptance

- GIVEN `--output /tmp/orphans.json`
- WHEN the run executes
- THEN the file exists with valid JSON matching REQ-003 and stdout is empty.

#### Edge cases

- `--output ../escape.json` → rejected, no file written.
- `--output -` or omitted → stdout.
- `--output openspec/scripts/output/run.json` → allowed (gitignored by REQ-009).

### REQ-007: Read-Only Invariant

The CLI SHALL open only read Neo4j sessions. The script SHALL fail-fast at import time if any `topology_repo` write helper is referenced. No write transaction SHALL be issued under any code path.

#### Acceptance

- GIVEN the script is started
- WHEN module imports are resolved
- THEN no write helper from `topology_repo` is imported.

#### Edge cases

- Adversarial `--relationship-types` value attempting Cypher injection → rejected by REQ-002 allowlist before any query runs.
- Driver-level write call attempt → fail-fast on first call.

### REQ-008: Neo4j URI Required, Credentials Never Logged

`--neo4j-uri` SHALL be required at runtime; the CLI SHALL also honor `$NEO4J_URI` as fallback. Missing both SHALL exit non-zero with stderr `error: --neo4j-uri (or $NEO4J_URI) required`. Credentials (`NEO4J_USER`, `NEO4J_PASSWORD`, or `--neo4j-user`/`--neo4j-password`) SHALL be accepted by the driver but SHALL NEVER appear in stdout, stderr, or the audit log — neither in cleartext, base64, nor partially redacted form.

#### Acceptance

- GIVEN no `--neo4j-uri` and no `$NEO4J_URI`
- WHEN the run starts
- THEN the CLI exits non-zero with a stderr error and no credentials appear anywhere.

#### Edge cases

- `$NEO4J_URI` set → used without `--neo4j-uri`.
- Wrong URI → driver connection error → stderr; credentials still not logged.

### REQ-009: `.gitignore` Coverage for `openspec/scripts/output/`

The repository `.gitignore` SHALL contain the entry `openspec/scripts/output/` (with trailing slash preferred). The entry SHALL match the directory and any file within it under `git check-ignore`.

#### Acceptance

- GIVEN the repo working tree
- WHEN `git check-ignore openspec/scripts/output/example.json` runs
- THEN the command exits 0 (path is ignored).

#### Edge cases

- File under the directory → ignored.
- `openspec/scripts/output` (no trailing slash) → also acceptable; trailing slash preferred.

### REQ-010: Synthetic Test Fixtures Only

Every automated test SHALL exercise a fake Neo4j driver or mock session. No test SHALL connect to a real Neo4j. Every CI ID in fixtures, examples, or assertions SHALL match `^ci-test-ap-orphan-\d{3,}$` or be a UUID-shaped opaque string. Tests SHALL fail if a fixture introduces a non-opaque ID or any name/IP/site/location field.

#### Acceptance

- GIVEN the test suite
- WHEN it runs under `cd backend && .venv/bin/python -m pytest`
- THEN no network connection to Neo4j is opened and every fixture ID matches the synthetic pattern.

#### Edge cases

- CI record carrying a `name` property → test fails (sanity guard against accidental real-data fixture).
- CI record with no `id` → that record is dropped, not surfaced.

## Scenarios

### SCN-001: Synthetic graph with N orphan APs

#### Setup

A fake Neo4j session returns 7 orphan APs with IDs `ci-test-ap-orphan-001` through `ci-test-ap-orphan-007` and 0 wired APs.

#### Action

Run `python openspec/scripts/cmdb_backfill_orphans.py --neo4j-uri bolt://fake --scope ap`.

#### Expected

Stdout JSON has `orphan_count: 7`, `ci_ids` containing exactly the 7 synthetic IDs in stable order. Stderr emits the audit line with `scope=ap`, `rels=DEPENDS_ON,HOSTED_ON`, `orphan_count=7`, `exit=0`. Exit code 0.

### SCN-002: Wired APs are excluded

#### Setup

Fake session returns 5 orphan APs plus 3 wired APs (each has at least one `DEPENDS_ON` or `HOSTED_ON` edge to a parent).

#### Action

Run the CLI with defaults.

#### Expected

`orphan_count: 5`, `ci_ids` contains only the 5 synthetic orphan IDs; no wired AP appears.

### SCN-003: `CONNECTS_TO` is not parentage (default scope)

#### Setup

Fake session returns 4 APs each with only `CONNECTS_TO` edges (no `DEPENDS_ON`, no `HOSTED_ON`).

#### Action

Run the CLI with defaults.

#### Expected

All 4 APs appear as orphans (`orphan_count: 4`); `CONNECTS_TO` does not satisfy parentage under the default allowlist.

### SCN-004: Custom relationship-types allowlist

#### Setup

Fake session returns 6 APs: 2 wired via `DEPENDS_ON` only, 2 wired via `HOSTED_ON` only, 2 truly orphan.

#### Action

Run with `--relationship-types HOSTED_ON`.

#### Expected

`orphan_count: 4`: the 2 `DEPENDS_ON`-only APs (no parent under `HOSTED_ON`) plus the 2 truly orphan APs.

### SCN-005: `--output` writes a JSON file

#### Setup

Empty temp directory; fake session returns 3 orphan APs.

#### Action

Run with `--output /tmp/<run-id>-orphans.json`.

#### Expected

File exists, parses as JSON matching REQ-003. Stdout is empty. Stderr audit line is emitted.

### SCN-006: Default invocation emits pure JSON to stdout

#### Setup

Fake session returns 2 orphan APs.

#### Action

Run with no flags except `--neo4j-uri bolt://fake`.

#### Expected

Stdout is exactly the JSON object (no leading/trailing prose); stderr emits the single audit line; exit 0.

### SCN-007: Stderr audit line shape

#### Setup

Any successful run configuration (use SCN-006).

#### Action

Capture stderr to a string.

#### Expected

Exactly one line matching `ts=... query_hash=<sha256-8+> scope=ap rels=DEPENDS_ON,HOSTED_ON orphan_count=<int> exit=0`. The line MUST NOT contain any CI ID. Stdout remains pure JSON.

### SCN-008: `--scope switch` rejected

#### Setup

No setup; fake session is wired but MUST NOT be called.

#### Action

Run with `--scope switch`.

#### Expected

Exit code non-zero. Stderr contains `error: invalid --scope switch; allowed: ap`. No Neo4j query is executed; no `query_hash` emitted.

### SCN-009: Missing Neo4j URI

#### Setup

No `--neo4j-uri`; `$NEO4J_URI` unset.

#### Action

Run with no URI flags or env.

#### Expected

Exit non-zero. Stderr contains `error: --neo4j-uri (or $NEO4J_URI) required`. No credentials (user/password) appear in stdout or stderr. No Neo4j connection attempted.

### SCN-010: Large graph safety cap

#### Setup

Fake session returns 15,000 orphan APs (IDs `ci-test-ap-orphan-001` ... `ci-test-ap-orphan-15000`).

#### Action

Run with defaults.

#### Expected

`orphan_count: 10000` (cap reached). `ci_ids` length is 10000. Stderr audit line includes `orphan_count=10000` and an additional `cap_reached=true` marker. Exit 0.

### SCN-011: Schema drift fail-fast

#### Setup

Fake session raises a `ClientError` whose message references a missing label (e.g. `Neo4jError: label AccessPoint not found`).

#### Action

Run with defaults.

#### Expected

Exit non-zero. Stderr contains `error: missing label AccessPoint in schema`. No partial output emitted. Audit line is emitted with `exit=1`.

### SCN-012: `.gitignore` enforcement

#### Setup

Repo working tree with `.gitignore` containing `openspec/scripts/output/`.

#### Action

A test creates `openspec/scripts/output/probe.json` and invokes `git check-ignore` against it; the test reads the `.gitignore` file and asserts the pattern is present.

#### Expected

`git check-ignore` exits 0 (path is ignored). `.gitignore` contains a line matching `^openspec/scripts/output/?$`. No orphan report can be committed.

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
| SCN-010 | Safety cap | WHEN orphan APs exceed 10,000 | THEN `orphan_count` reflects 10,000 cap |
| SCN-011 | Schema drift | WHEN Neo4j reports a missing label | THEN exit non-zero with the label name in stderr |
| SCN-012 | `.gitignore` | WHEN the script would write into `openspec/scripts/output/` | THEN git treats the path as ignored |

## Out of Scope

- **Auto-write / auto-wiring of relationships** (deferred to P3b). The script is read-only by design.
- **Heuristics** — no name-matching, IP-matching, site-matching, or relationship inference. Pure dry-run detection.
- **Non-AP CI types** — switch, router, server, etc. are out of scope; only `ap` is accepted in this slice.
- **Enrichment beyond opaque CI IDs** — no names, IPs, sites, locations, or relationship attributes in stdout.
- **Modify `topology_repo` writers or `services/snmp_service.py`** — the script reuses read helpers only.
- **Queue/legacy collector parity** — this is offline SDD tooling; it does not run inside the API process.
- **"Explain" mode or per-orphan narrative** — flat list of opaque IDs only.
- **Real customer data** — CI IDs are opaque UUIDs; examples use placeholders (`ci-example-uuid-NNN`, `ci-test-ap-orphan-NNN`). Names, IPs, sites, locations, and credentials never appear in this spec, in any test fixture, in any example, or in any captured output.
- **`CONNECTS_TO` parentage** — explicitly excluded per `correlation-topology-guide.md`.
