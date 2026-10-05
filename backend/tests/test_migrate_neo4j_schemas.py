"""Unit tests for the migration runners (T5..T9).

T5–T7 exercise the DRY wrapper ``migrate_neo4j_schemas.py``; T8/T9 are
regression tests for the refactored ``migrate_ci_event_indexes.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import scripts.migrate_ci_event_indexes as ci_runner
import scripts.migrate_neo4j_schemas as wrapper
from scripts._apply_cypher import ApplyResult, CypherStatementError, StatementError

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
