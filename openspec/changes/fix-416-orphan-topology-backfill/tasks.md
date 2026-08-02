# Tasks: CMDB Orphan Topology Backfill (P3a of fix #416)

## Overview
Ships `openspec/scripts/cmdb_backfill_orphans.py`, a read-only offline CLI that discovers Access Points with no upstream `DEPENDS_ON|HOSTED_ON` edge so an operator can manually wire them in internal CMDB tooling. No auto-write, no heuristics, no enrichment beyond opaque CI IDs. The 10 work units below cover all 13 REQs (REQ-001..010 + REQ-100..102), all 14 SCNs (SCN-001..012 + SCN-100..101), and all 15 ADs (AD-01..15). Tests run against a duck-typed `FakeSession` using synthetic IDs only (`ci-test-ap-orphan-NNN` / opaque UUIDs); no real Neo4j connection, no real customer data.

## Review Workload Forecast

| File | LoC |
|---|---|
| `openspec/scripts/__init__.py` | 0 |
| `openspec/scripts/cmdb_backfill_orphans.py` | ~260 |
| `openspec/scripts/tests/__init__.py` | 0 |
| `openspec/scripts/tests/conftest.py` | ~80 |
| `openspec/scripts/tests/test_cmdb_backfill_orphans.py` | ~360 |
| `openspec/scripts/OPERATOR_RUNBOOK.md` | ~50 |
| `.gitignore` (1 line appended) | 1 |
| `CHANGELOG.md` (1 entry) | ~5 |
| **Total** | **~756** |

Within the 800-line review budget. Forecast uses python source lines + markdown lines (counts every line as one).

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | PR | Focused test | Harness | Rollback |
|------|------|----|--------------|---------|----------|
| WU-1 | Scaffold + gitignore | PR 1 | `cd backend && .venv/bin/python -m pytest --collect-only openspec/scripts/tests/` | N/A — pure import | delete 3 new files + revert 1 .gitignore line |
| WU-2 | Scope + rels validators | PR 1 | `pytest -k "validate_scope or validate_relationship_types or allowlist"` | N/A — pure functions | 2 functions in module |
| WU-3 | JSON schema + output routing | PR 1 | `pytest -k "build_output_payload or write_output or opaque"` | N/A — pure functions + tmp_path | `build_output_payload`, `write_output` |
| WU-4 | stderr audit line | PR 1 | `pytest -k "emit_audit_line"` | N/A — pure function | `emit_audit_line` |
| WU-5 | Path safety | PR 1 | `pytest -k "resolve_output_path or traversal"` | N/A — pure | `resolve_output_path` |
| WU-6 | Read-only invariant | PR 1 | `pytest -k "write_token or read_only or ast_scan"` | N/A — AST + FakeSession.execute_write | AST scan + session guard |
| WU-7 | URI + credentials | PR 1 | `pytest -k "neo4j_uri or credential or env_fallback"` | N/A — pure + lazy import | `_resolve_neo4j_uri`, `_open_neo4j` |
| WU-8 | Fake driver + Cypher | PR 1 | `pytest -k "build_query or compute_query_hash or discover_orphans or fake_session or schema_drift or cap"` | FakeSession — no real Neo4j | 3 functions + conftest fixtures |
| WU-9 | CLI wiring + integration | PR 1 | `pytest -k "main or integration"` | FakeSession via monkeypatch | `main`, `parse_args` |
| WU-10 | Runbook + changelog + verify | PR 1 | `pytest openspec/scripts/tests/ -v` | N/A — docs | 2 docs files + 1 line |

## Work Unit Details

### WU-1 — Scaffold + gitignore (REQ-009, REQ-102, AD-06, AD-11)
- [ ] T-001 [CONFIG] Create `openspec/scripts/__init__.py` (empty package marker). Commit: `chore(scripts): add openspec/scripts package marker`.
- [ ] T-002 [CONFIG] Create `openspec/scripts/tests/__init__.py` (empty). Commit: `chore(scripts): add tests package marker`.
- [ ] T-003 [CONFIG] Create `openspec/scripts/tests/conftest.py` with `SYNTHETIC_ID_RE = re.compile(r"^ci-test-ap-orphan-\d{3,}$")` + autouse `validate_fixture_ids` fixture that fails any test touching a non-synthetic ID (REQ-010, AD-13). Commit: `chore(scripts): add conftest with synthetic-id guard`.
- [ ] T-004 [CONFIG] Append `openspec/scripts/output/` to `.gitignore`. Commit: `chore(gitignore): ignore openspec/scripts/output`.
- [ ] T-005 [RED] Write SCN-012 test asserting `git check-ignore openspec/scripts/output/probe.json` exits 0 and `.gitignore` contains `^openspec/scripts/output/?$`. Pair with T-004. Commit: `test(scripts): assert gitignore covers output dir`.

### WU-2 — Validation layer (REQ-001, REQ-002, SCN-008, AD-01, AD-08)
- [ ] T-006 [RED] Tests: `validate_scope("ap")` passes; `validate_scope("switch")` raises `ValueError("error: invalid --scope switch; allowed: ap")`; no Neo4j call attempted. Pair with T-007.
- [ ] T-007 [GREEN] Implement `validate_scope(scope)` using `ALLOWED_SCOPES = frozenset({"ap"})`; raise before any driver call (REQ-001, AD-01). Commit: `feat(orphan-cli): validate --scope against ap allowlist`.
- [ ] T-008 [RED] Tests: `validate_relationship_types(None)` defaults to `["DEPENDS_ON","HOSTED_ON"]`; rejects `CONNECTS_TO`; rejects raw Cypher `"MATCH (n) DELETE n"`; dedupes duplicates; preserves order. Pair with T-009.
- [ ] T-009 [GREEN] Implement `validate_relationship_types(types)` using `ALLOWED_RELATIONSHIP_TYPES = frozenset({"DEPENDS_ON","HOSTED_ON","MANAGES","RUNS_ON"})`; reject anything else before any Neo4j call (REQ-002, AD-08). Commit: `feat(orphan-cli): validate --relationship-types allowlist`.

### WU-3 — Output layer (REQ-003, REQ-004, AD-03, AD-05)
- [ ] T-010 [RED] Tests: `build_output_payload` returns exactly `{as_of, scope, relationship_types, orphan_count, ci_ids}`; `orphan_count == len(ci_ids)`; ISO 8601 UTC trailing `Z`; non-opaque values stripped; duplicates deduped (SCN-001, REQ-004). Pair with T-011.
- [ ] T-011 [GREEN] Implement `build_output_payload(as_of, scope, rels, ids)` filtering through `SYNTHETIC_ID_RE` + UUID-shape fallback; `dict.fromkeys` for dedupe; `datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")` for `as_of`. Commit: `feat(orphan-cli): build strict json output envelope`.
- [ ] T-012 [RED] Tests: `write_output(payload, path)` writes UTF-8 JSON file with `indent=2` + trailing newline; stdout empty when path given; stdout receives pure JSON when path is `None`. Pair with T-013.
- [ ] T-013 [GREEN] Implement `write_output(payload, output_path)` returning the serialized string; route via `_route_output`. Commit: `feat(orphan-cli): route output to file or stdout`.

### WU-4 — Audit layer (REQ-005, AD-07)
- [ ] T-014 [RED] Tests: `emit_audit_line` produces single line in exact order `ts=... query_hash=<≥8 hex> scope=... rels=... orphan_count=... exit=... cap_reached=<bool>`; never includes `ci_ids` substrings; emits to stderr only (captured via `capsys`). Pair with T-015.
- [ ] T-015 [GREEN] Implement `emit_audit_line(stream, *, ts, query_hash, scope, rels, orphan_count, exit, cap_reached=False)` writing space-joined key=value pairs + `\n`; no f-string interpolation of `ci_ids` (REQ-005, AD-07). Commit: `feat(orphan-cli): emit stderr audit line`.

### WU-5 — Path safety (REQ-006, AD-02)
- [ ] T-016 [RED] Tests: `resolve_output_path` returns `None` for `"-"` or `""`; raises `ValueError("error: --output '...' escapes working tree")` for `--output ../escape.json`; accepts absolute path inside cwd; accepts `openspec/scripts/output/x.json`. Pair with T-017.
- [ ] T-017 [GREEN] Implement `resolve_output_path(path)` via `Path.resolve(strict=False)` + `is_relative_to(Path.cwd().resolve())`. Commit: `feat(orphan-cli): enforce output path inside cwd`.

### WU-6 — Read-only invariant (REQ-007, AD-09, AD-12)
- [ ] T-018 [RED] AST-scan test walking `cmdb_backfill_orphans.py` rejects any string literal matching `WRITE_TOKEN_RE = re.compile(r"\b(WRITE|MERGE|CREATE|DELETE|SET)\b", re.IGNORECASE)`; parametrized over good/bad fixtures. Pair with T-019.
- [ ] T-019 [GREEN] Implement `test_no_write_tokens_in_any_literal` AST scan + runtime `FakeSession.execute_write` raising `AssertionError("write attempted")`. Commit: `feat(orphan-cli): enforce read-only invariant`.
- [ ] T-020 [TEST] Module-AST test asserting `topology_repo` is never imported (`sys.modules` snapshot + AST `Import`/`ImportFrom` scan). Commit: `test(scripts): guard no-topology_repo-import`.

### WU-7 — Credentials (REQ-008, AD-15)
- [x] T-021 [RED] Tests: `_resolve_neo4j_uri` uses `--neo4j-uri` when given; falls back to `$NEO4J_URI`; raises `ValueError("error: --neo4j-uri (or $NEO4J_URI) required")` when both missing; never echoes value to stdout/stderr. Pair with T-022.
- [x] T-022 [GREEN] Implement `_resolve_neo4j_uri(args, env)` returning resolved URI string or raising. Commit: `feat(orphan-cli): resolve neo4j uri from flag or env`.
- [x] T-023 [RED] Tests: `_open_neo4j(uri)` does NOT trigger `import neo4j` when module loads (assert via `sys.modules` snapshot); only imports inside the function; connection errors surface without echoing credentials. Pair with T-024.
- [x] T-024 [GREEN] Implement `_open_neo4j(uri)` with deferred `from neo4j import GraphDatabase` inside the function body (REQ-008, AD-15). Commit: `feat(orphan-cli): lazy-open neo4j driver`.

### WU-8 — Fake driver + Cypher (SCN-001..012, REQ-009/010, AD-13, AD-14)
- [x] T-025 [RED] Tests: `build_query(scope="ap", rels=("DEPENDS_ON","HOSTED_ON"), cap=10000)` produces Cypher with `MATCH (n:CI:AccessPoint)`, `NOT EXISTS { ... type(r) IN $relationship_types }`, `RETURN n.id AS ci_id`, `LIMIT $cap`; params include `relationship_types` + `cap`. Pair with T-026.
- [x] T-026 [GREEN] Implement `build_query(scope, rel_types, cap=MAX_ORPHAN_CAP)` returning `(query_str, params)` parameterized; `MAX_ORPHAN_CAP = 10_000` (AD-09, AD-14). Commit: `feat(orphan-cli): parameterize cypher orphan query`.
- [x] T-027 [RED] Tests: `compute_query_hash(query, params)` returns sha256 hex ≥ 8 chars; stable for same input; different params → different hash; never hashes CI IDs. Pair with T-028.
- [x] T-028 [GREEN] Implement `compute_query_hash(query, params)` using `hashlib.sha256` over canonical JSON; return first 16 hex chars (REQ-005). Commit: `feat(orphan-cli): hash query for audit`.
- [x] T-029 [CONFIG] Add `FakeRecord`/`FakeResult`/`FakeSession` to `conftest.py` with `session.queries` capture list; `FakeSession.run(query, **params)` returns `FakeResult` or raises configured `Neo4jError`; add `fake_session` factory fixture returning rows `{"ci_id": "ci-test-ap-orphan-NNN"}`. Commit: `test(scripts): add fake neo4j session seam`.
- [x] T-030 [RED] Parametrized scenario tests: SCN-001 (7 orphans), SCN-002 (5 orphans + 3 wired excluded), SCN-003 (4 APs only `CONNECTS_TO` → 4 orphans), SCN-004 (`HOSTED_ON` only → 4 orphans), SCN-006 (stdout pure JSON, no extra prose). Pair with T-031.
- [x] T-031 [GREEN] Implement `discover_orphans(session, scope, rels, cap)` invoking `session.run(query, **params)`; iterate result rows via `.get("ci_id")`; dedupe + cap; on `ClientError` matching `label \w+ not found` raise `RuntimeError("error: missing label <name> in schema")` (SCN-011). Commit: `feat(orphan-cli): discover orphans via fake session`.
- [x] T-032 [TEST] SCN-010 cap test: feed 15_000 synthetic IDs, assert `orphan_count == 10000`, `cap_reached=True`, audit line includes `cap_reached=true`. Commit: `test(scripts): enforce 10k orphan cap`.

### WU-9 — CLI wiring (SCN-005, SCN-007, SCN-008, SCN-009, AD-01)
- [ ] T-033 [RED] Integration tests for `main(argv)` via `capsys` + monkeypatched `_open_neo4j` → `FakeSession`: SCN-005 (`--output <tmp>/file.json` writes file + empty stdout), SCN-007 (audit line shape on success), SCN-008 (`--scope switch` → exit != 0, no `query_hash`), SCN-009 (missing URI → exit != 0, no credentials logged). Pair with T-034.
- [ ] T-034 [GREEN] Implement `parse_args` (`argparse`) + `main(argv=None)` orchestrating validators → driver → output → audit; ensure `exit=` reflects actual `sys.exit` code in audit. Commit: `feat(orphan-cli): wire main entrypoint`.

### WU-10 — Docs + CHANGELOG + final verify (REQ-100, REQ-101, REQ-102, SCN-100, SCN-101)
- [ ] T-035 [DOCS] Create `openspec/scripts/OPERATOR_RUNBOOK.md` with the 4-step sequence from proposal §Operator runbook; never instruct copying JSON output into repo tree (REQ-100, SCN-100). Commit: `docs(scripts): add orphan discovery runbook`.
- [ ] T-036 [DOCS] Append `[Unreleased]` → `### Added` entry to `CHANGELOG.md` referencing `openspec/scripts/cmdb_backfill_orphans.py`; no customer data, no real CI IDs (REQ-101, SCN-101). Commit: `docs(changelog): note orphan discovery cli`.
- [ ] T-037 [TEST] SCN-100 reads runbook file, asserts 4 steps + no "copy into repo" instruction. SCN-101 reads `CHANGELOG.md`, asserts `[Unreleased]` + `### Added` + CLI path. Commit: `test(scripts): assert runbook and changelog entries`.
- [ ] T-038 [VERIFY] Run `cd backend && .venv/bin/python -m pytest openspec/scripts/tests/ -v` — all green, no skips, no Neo4j dependency. Commit: `chore(scripts): mark verify checklist complete`.

## Final Verification
- [ ] T-039 Full backend suite: `cd backend && .venv/bin/python -m pytest -q` — no regressions vs. baseline.
- [ ] T-040 Lint: `cd backend && .venv/bin/python -m ruff check openspec/scripts/` — clean.
- [ ] T-041 Privacy sweep: `grep -rE "<issue-derived rejection-test tokens and production IP from issue #416>" openspec/scripts/` — must return zero results.

## Strict TDD Discipline
- Every GREEN task is preceded by its RED task in the same WU.
- All fixtures use `ci-test-ap-orphan-NNN` (or UUID-shaped opaque strings) — never real names/IPs/sites.
- `conftest.py` autouse fixture fails any test touching a non-synthetic ID.
- After each WU: `cd backend && .venv/bin/python -m pytest openspec/scripts/tests/ -v` must stay green.
- Test count never decreases between GREEN commits; no skipped tests.

## Out of Scope (reaffirmed)
- No auto-write / auto-wiring of relationships (deferred P3b).
- No naming, IP, site, or location heuristics.
- No non-AP CI types (`switch`, `router`, `server` rejected).
- No modification of `backend/repositories/topology_repo` writers or `backend/services/snmp_service.py`.
- No queue / legacy collector parity.
- No "explain" mode or per-orphan enrichment beyond opaque IDs.
- P3b (auto-write) and P3c (legacy collector parity) remain future work.

## Coverage Map
- **REQ-001** → WU-2 (T-006/T-007). **REQ-002** → WU-2 (T-008/T-009). **REQ-003** → WU-3 (T-010/T-011). **REQ-004** → WU-3 (T-010/T-011). **REQ-005** → WU-4 (T-014/T-015) + WU-8 (T-027/T-028). **REQ-006** → WU-5 (T-016/T-017) + WU-3 (T-012/T-013). **REQ-007** → WU-6 (T-018/T-019/T-020). **REQ-008** → WU-7 (T-021..T-024). **REQ-009** → WU-1 (T-004/T-005). **REQ-010** → WU-1 (T-003) + enforced across all WUs. **REQ-100** → WU-10 (T-035/T-037). **REQ-101** → WU-10 (T-036/T-037). **REQ-102** → WU-1 (T-003) + WU-10 (T-038).
- **SCN-001..004, SCN-006** → WU-8 (T-030/T-031). **SCN-005** → WU-9 (T-033/T-034). **SCN-007** → WU-4 (T-014/T-015) + WU-9 (T-033/T-034). **SCN-008** → WU-2 (T-006/T-007) + WU-9 (T-033/T-034). **SCN-009** → WU-7 (T-021/T-022) + WU-9 (T-033/T-034). **SCN-010** → WU-8 (T-032). **SCN-011** → WU-8 (T-031). **SCN-012** → WU-1 (T-004/T-005). **SCN-100** → WU-10 (T-035/T-037). **SCN-101** → WU-10 (T-036/T-037).
- **AD-01** → WU-2 + WU-9. **AD-02** → WU-5. **AD-03/AD-05** → WU-3 + T-041. **AD-04** → constraint (no task; design excludes). **AD-06** → WU-1. **AD-07** → WU-4. **AD-08** → WU-2. **AD-09/AD-12** → WU-6. **AD-10** → all WUs (TDD). **AD-11** → WU-1 + WU-10. **AD-13/AD-14** → WU-8. **AD-15** → WU-7.
- **Threat matrix**: N/A per design §Threat Matrix (no routing/shell/subprocess/VCS boundary); rationale preserved in design.md.
