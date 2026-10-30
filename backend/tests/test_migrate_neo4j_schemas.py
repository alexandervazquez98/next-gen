"""Unit tests for the migration runners (T5..T9).

T5–T7 exercise the DRY wrapper ``migrate_neo4j_schemas.py``; T8/T9 are
regression tests for the refactored ``migrate_ci_event_indexes.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import scripts.migrate_ci_event_indexes as ci_runner
import scripts.migrate_neo4j_schemas as wrapper
from scripts._apply_cypher import (
    ApplyResult,
    CypherStatementError,
    StatementError,
    _split_statements,
    apply_cypher_file,
)

_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

# ---------- T5..T7: DRY wrapper ----------


def _seed(t, names):
    d = t / "migrations"
    d.mkdir()
    for n in names:
        (d / n).write_text("// stub\n", encoding="utf-8")
    return d


def test_wrapper_iterates_in_lexicographic_order_skipping_008(tmp_path, monkeypatch):
    """T5: every migration except 008, in sorted order."""
    m = _seed(
        tmp_path,
        ["010_baz.cypher", "001_foo.cypher", "008_ci_event_indexes.cypher", "007_bar.cypher"],
    )
    monkeypatch.setattr(wrapper, "_MIGRATIONS_DIR", m)
    seen = []
    monkeypatch.setattr(
        wrapper,
        "apply_cypher_file",
        lambda d, fp, *, log=None: seen.append(Path(fp).name) or ApplyResult(1, []),
    )
    assert wrapper.main() == 0
    assert seen == ["001_foo.cypher", "007_bar.cypher", "010_baz.cypher"]


def test_wrapper_exits_2_on_statement_error(tmp_path, monkeypatch):
    """T6: CypherStatementError from any migration maps to exit code 2."""
    m = _seed(tmp_path, ["001_foo.cypher"])
    monkeypatch.setattr(wrapper, "_MIGRATIONS_DIR", m)
    boom = CypherStatementError(
        [StatementError(statement="X", exception=RuntimeError("e"), index=1)]
    )

    def boom_apply(d, fp, *, log=None):
        raise boom

    monkeypatch.setattr(wrapper, "apply_cypher_file", boom_apply)
    assert wrapper.main() == 2


def test_wrapper_exits_0_on_clean_run(tmp_path, monkeypatch):
    """T7: when every apply_cypher_file returns successfully, exit code is 0."""
    m = _seed(tmp_path, ["001_foo.cypher", "008_ci_event_indexes.cypher", "010_baz.cypher"])
    monkeypatch.setattr(wrapper, "_MIGRATIONS_DIR", m)
    monkeypatch.setattr(wrapper, "apply_cypher_file", lambda d, fp, *, log=None: ApplyResult(2, []))
    assert wrapper.main() == 0


# ---------- Neo4j 5 migration syntax regression ----------


class _RecordingSession:
    def __init__(self):
        self.queries = []

    def run(self, query, **params):
        self.queries.append(query)
        return []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _RecordingDriver:
    def __init__(self):
        self.session_instance = _RecordingSession()

    def session(self, **kwargs):
        return self.session_instance


def test_rtu_sensor_schema_uses_neo4j_5_index_syntax():
    """All non-constrained indexes in migration 001 use Neo4j 5.x ``ON`` syntax."""
    migration = Path(__file__).resolve().parents[1] / "migrations" / "001_rtu_sensor_schema.cypher"
    driver = _RecordingDriver()

    result = apply_cypher_file(driver, migration)

    assert result.statements_run == 4
    index_statements = [
        query for query in driver.session_instance.queries if query.startswith("CREATE INDEX")
    ]
    assert index_statements == [
        "CREATE INDEX sensor_rtu_addr_type IF NOT EXISTS FOR (s:Sensor) "
        "ON (s.rtu_id, s.register_addr, s.sensor_type)",
        "CREATE INDEX sensor_rtu_id IF NOT EXISTS FOR (s:Sensor) ON (s.rtu_id)",
    ]


# ---------- Neo4j 5 migration corpus compatibility ----------


def test_split_statements_drops_sql_style_comment_banners():
    """Banners written with ``--`` are not Cypher comments and must be dropped.

    Neo4j 5.x rejects them with ``Invalid input '-': expected``; the Cypher
    line comment marker is ``//``.
    """
    content = "\n".join(
        [
            "-- ── Device Node ──────────────────────────────",
            "-- Device represents any generic device.",
            "--",
            "// a real Cypher comment",
            "CREATE CONSTRAINT device_id_unique IF NOT EXISTS",
            "FOR (d:Device) REQUIRE d.id IS UNIQUE;",
        ]
    )

    assert _split_statements(content) == [
        "CREATE CONSTRAINT device_id_unique IF NOT EXISTS FOR (d:Device) REQUIRE d.id IS UNIQUE"
    ]


def test_split_statements_keeps_comment_markers_inside_string_literals():
    """A ``--`` or ``//`` inside a literal is content, not a comment."""
    content = "\n".join(
        [
            "MATCH (u:User {note: 'a -- b'})",
            "RETURN u.url AS url;",
            "// trailing comment",
        ]
    )

    assert _split_statements(content) == ["MATCH (u:User {note: 'a -- b'}) RETURN u.url AS url"]


def test_migration_corpus_never_emits_a_double_dash_statement():
    """No migration file may produce a statement starting with ``--``."""
    offenders = []
    for path in sorted(_MIGRATIONS_DIR.glob("*.cypher")):
        for statement in _split_statements(path.read_text(encoding="utf-8")):
            if statement.lstrip().startswith("--"):
                offenders.append(f"{path.name}: {statement[:60]}")

    assert offenders == []


def test_neo4j_migration_corpus_contains_no_postgres_ddl():
    """The Neo4j runner must never receive PostgreSQL DDL.

    Neo4j 5.x rejects it with ``Invalid input 'TABLE': expected``.
    """
    postgres_ddl = re.compile(
        r"\b(ALTER\s+TABLE|CREATE\s+TABLE|DROP\s+TABLE|ADD\s+COLUMN|CREATE\s+INDEX\s+CONCURRENTLY)\b",
        re.IGNORECASE,
    )
    offenders = []
    for path in sorted(_MIGRATIONS_DIR.glob("*.cypher")):
        for statement in _split_statements(path.read_text(encoding="utf-8")):
            if postgres_ddl.search(statement):
                offenders.append(f"{path.name}: {statement[:80]}")

    assert offenders == []


# ---------- T8, T9: regression for refactored migrate_ci_event_indexes.py ----------


class _Session:
    """Stub session: yields a CI duplicate row on the first :CI preflight query if asked."""

    def __init__(self, ci_dup):
        self.queries, self._ci_done, self._ci_dup = [], False, ci_dup

    def run(self, q, **p):
        self.queries.append(q)
        if "MATCH (c:CI)" in q and self._ci_dup and not self._ci_done:
            self._ci_done = True
            return [{"id": "dup-1", "n": 2}]
        return []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Driver:
    def __init__(self, s):
        self._s = s

    def session(self, **k):
        return self._s


def _seed_008(t):
    d = t / "migrations"
    d.mkdir()
    tgt = d / "008_ci_event_indexes.cypher"
    tgt.write_text(
        "CREATE CONSTRAINT ci_id_unique IF NOT EXISTS\n" "FOR (c:CI) REQUIRE c.id IS UNIQUE;\n",
        encoding="utf-8",
    )
    return tgt


def test_preflight_aborts_with_exit_1_on_duplicate_ci_ids(tmp_path, monkeypatch):
    """T8: preflight detects :CI duplicates; SystemExit(1) before any statement runs."""
    _seed_008(tmp_path)
    monkeypatch.setattr(ci_runner, "_MIGRATIONS_DIR", tmp_path / "migrations")
    session, calls = _Session(ci_dup=True), []
    driver = _Driver(session)

    def fake(d, fp, *, log=None):
        calls.append(Path(fp))
        return ApplyResult(1, [])

    monkeypatch.setattr(ci_runner, "apply_cypher_file", fake)
    with pytest.raises(SystemExit) as exc_info:
        ci_runner.apply_ci_event_indexes(driver=driver)
    assert exc_info.value.code == 1
    assert calls == []
    assert any("MATCH (c:CI)" in q for q in session.queries)


def test_happy_path_runs_through_utility(tmp_path, monkeypatch):
    """T9: with no duplicates, the utility is called with the migration path."""
    target = _seed_008(tmp_path)
    monkeypatch.setattr(ci_runner, "_MIGRATIONS_DIR", tmp_path / "migrations")
    session, calls = _Session(ci_dup=False), []
    driver = _Driver(session)

    def fake(d, fp, *, log=None):
        calls.append(Path(fp))
        return ApplyResult(1, [])

    monkeypatch.setattr(ci_runner, "apply_cypher_file", fake)
    ci_runner.apply_ci_event_indexes(driver=driver)
    assert calls == [target]
    assert any("MATCH (c:CI)" in q for q in session.queries)
    assert any("MATCH (e:Event)" in q for q in session.queries)
