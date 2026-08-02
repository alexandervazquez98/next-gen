# Design: CMDB Orphan Topology Backfill

## Technical Approach

Single-file read-only Python CLI under `openspec/scripts/` running a parameterized Cypher NOT EXISTS query against Neo4j 5.x. Emits a JSON envelope of opaque CI IDs + one stderr audit line. Strict-TDD with `FakeSession` seam. No `topology_repo` import.

## Architecture Decisions

| ID | Decision | Choice |
|---|---|---|
| AD-01 | Scope | `--scope ap` only; reject pre-query |
| AD-02 | Output | Single JSON to stdout or `--output` |
| AD-03 | Enrichment | Opaque CI IDs only (UUID + `ci-test-ap-orphan-NNN`) |
| AD-04 | Heuristics | None |
| AD-05 | Customer data | Zero real IDs/names/IPs/sites |
| AD-06 | `.gitignore` | Append `openspec/scripts/output/` |
| AD-07 | Audit | stderr `ts,query_hash,scope,rels,orphan_count,exit,cap_reached` |
| AD-08 | Rel allowlist | `{DEPENDS_ON,HOSTED_ON,MANAGES,RUNS_ON}`; `CONNECTS_TO` excluded |
| AD-09 | Read-only | AST scan rejects write tokens; runtime `session.run` only |
| AD-10 | TDD | `cd backend && .venv/bin/python -m pytest`; synthetic IDs |
| AD-11 | Module | One file + `__init__.py` + `tests/` (<300 LoC) |
| AD-12 | Reuse | Self-contained; NO `topology_repo` import |
| AD-13 | Fake driver | Local `FakeSession` via duck-typed seam |
| AD-14 | Cap | `MAX_ORPHAN_CAP=10_000`; `cap_reached=true` |
| AD-15 | neo4j import | Lazy inside `_open_neo4j()` |

AD-01..AD-10 = locked hard constraints. AD-11..AD-15 = derived.

## Data Flow

```
parse_args → validate_scope → validate_relationship_types
              │ build_query + compute_query_hash
              ▼
discover_orphans(session) → session.run(query, **params)  [FakeSession]
              │
              ▼
          _ci_ids (opaque)
              │
   ┌──────────┴──────────┐
   ▼                     ▼
write_output → stdout/file   emit_audit_line → stderr
                                  ▼
                              exit 0|1|2
```

## File Changes

| File | Action | Description |
|---|---|---|
| `openspec/scripts/__init__.py` | Create | Package marker. |
| `openspec/scripts/cmdb_backfill_orphans.py` | Create | The CLI (~200-280 LoC). |
| `openspec/scripts/tests/__init__.py` | Create | Test package marker. |
| `openspec/scripts/tests/conftest.py` | Create | `FakeSession`/`FakeRecord`/`FakeResult` + fixture. |
| `openspec/scripts/tests/test_cmdb_backfill_orphans.py` | Create | SCN-001..012 + REQ-004/006/007/008. |
| `openspec/scripts/OPERATOR_RUNBOOK.md` | Create | Four-step operator sequence (REQ-100). |
| `.gitignore` | Modify | Append `openspec/scripts/output/`. |
| `CHANGELOG.md` | Modify | `[Unreleased]` → `### Added` (REQ-101). |

## Interfaces / Contracts

```python
DEFAULT_RELATIONSHIP_TYPES = ("DEPENDS_ON", "HOSTED_ON")
ALLOWED_RELATIONSHIP_TYPES = frozenset({"DEPENDS_ON","HOSTED_ON","MANAGES","RUNS_ON"})
ALLOWED_SCOPES = frozenset({"ap"})
MAX_ORPHAN_CAP = 10_000
AUDIT_KEYS = ("ts","query_hash","scope","rels","orphan_count","exit","cap_reached")
SYNTHETIC_ID_RE = re.compile(r"^ci-test-ap-orphan-\d{3,}$")
WRITE_TOKEN_RE = re.compile(r"\b(WRITE|MERGE|CREATE|DELETE|SET)\b", re.IGNORECASE)

def parse_args(argv) -> argparse.Namespace: ...
def validate_scope(scope: str) -> None: ...
def validate_relationship_types(types) -> list[str]: ...
def build_query(scope, rel_types) -> tuple[str, dict]: ...
def compute_query_hash(query, params) -> str: ...
def discover_orphans(session, scope, rel_types, cap) -> list[str]: ...
def emit_audit_line(stream, *, ts, query_hash, scope, rels,
                    orphan_count, exit, cap_reached=False) -> None: ...
def resolve_output_path(path: str) -> Path | None: ...
def write_output(payload: dict, output_path) -> None: ...
def _open_neo4j(uri: str): ...
def main(argv=None) -> int: ...
```

## Cypher Query (AD-09)

```cypher
MATCH (n:CI:AccessPoint)
WHERE NOT EXISTS {
  MATCH (n)-[r]->(m:CI)
  WHERE type(r) IN $relationship_types
}
RETURN n.id AS ci_id
LIMIT $cap
```

Direction matches `correlation-topology-guide.md` (dependent → dependency). `NOT EXISTS` short-circuits in 5.x. Parameters prevent injection. Catch `ClientError` matching `label \w+ not found` (SCN-011).

## Fake Driver Pattern (AD-13)

```python
class FakeRecord:
    def __init__(self, d): self._d = d
    def __getitem__(self, k): return self._d.get(k)
    def get(self, k, default=None): return self._d.get(k, default)

class FakeResult:
    def __init__(self, rows): self._rows = [FakeRecord(r) for r in rows]
    def __iter__(self): return iter(self._rows)

class FakeSession:
    def __init__(self, responses):
        self.queries: list[tuple[str, dict]] = []
        self._responses = responses
    def run(self, query, **params):
        self.queries.append((query, params))
        if isinstance(self._responses, Exception): raise self._responses
        return FakeResult(self._responses)
    def __enter__(self): return self
    def __exit__(self, *a): return False
```

Duck-types on `session.run(query, **params)` returning an iterable with `.get()`/indexing — a structural sub-protocol of `neo4j.Session`. No `isinstance` coupling.

## Path Safety (REQ-006)

```python
def resolve_output_path(path: str):
    if path in ("-", ""): return None
    p = Path(path)
    cwd = Path.cwd().resolve()
    resolved = (cwd / p).resolve(strict=False) if not p.is_absolute() \
               else p.resolve(strict=False)
    if not resolved.is_relative_to(cwd):
        raise ValueError(f"error: --output {path!r} escapes working tree")
    return resolved
```

Rejects `..` traversal, absolute paths outside cwd, symlinks resolving outside cwd.

## Read-Only Invariant (REQ-007 / AD-09)

```python
def test_no_write_tokens_in_any_literal():
    import ast, pathlib
    tree = ast.parse(pathlib.Path("openspec/scripts/cmdb_backfill_orphans.py")
                     .read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not WRITE_TOKEN_RE.search(node.value)
```

Runtime companion: `FakeSession.execute_write` raises `AssertionError("write attempted")`.

## Testing Strategy

| Layer | Scope | How |
|---|---|---|
| Unit | Validators, `build_query`, `compute_query_hash`, `emit_audit_line`, `resolve_output_path`, `discover_orphans` | Function-level + parametrize |
| Scenario | SCN-001..012 | `pytest.mark.parametrize` mirroring delta spec |
| Invariant | REQ-004/005/006/007/008/010 | AST scan + stderr/stdout capture + `tmp_path` + fixture-ID regex |

100% line coverage. Run: `cd backend && .venv/bin/python -m pytest`.

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, or process-integration boundary. CLI opens one read-only Bolt session + stdout/file/stderr only.

## Migration / Rollout

No migration. No DB writes. Rollback = delete 5 new files + `.gitignore` line + changelog entry.

## Open Questions

Deferred to P3b: `--max-orphans` flag, additional scopes.