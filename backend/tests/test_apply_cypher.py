"""Unit tests for the _apply_cypher utility module (T1..T4)."""

from __future__ import annotations

import pytest
from scripts._apply_cypher import ApplyResult, CypherStatementError, apply_cypher_file


class _Session:
    def __init__(self, fail_on=None, exc=None):
        self.queries, self.fail_on, self.exc = [], fail_on, exc

    def run(self, q, **p):
        self.queries.append(q)
        if self.fail_on is not None and len(self.queries) == self.fail_on:
            raise self.exc or RuntimeError("boom")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Driver:
    def __init__(self, s):
        self._s = s

    def session(self, **k):
        return self._s


def _w(t, n, c):
    p = t / n
    p.write_text(c, encoding="utf-8")
    return p


def test_apply_cypher_file_strips_line_comments(tmp_path):
    """T1: line comments are stripped before splitting on ';'."""
    f = _w(
        tmp_path,
        "x.cypher",
        "// leading\nCREATE CONSTRAINT a IF NOT EXISTS;\n// mid\nCREATE INDEX b;\n",
    )
    drv = _Driver(_Session())
    result = apply_cypher_file(drv, f)
    assert isinstance(result, ApplyResult)
    assert result.statements_run == 2
    assert result.errors == []
    assert drv._s.queries == ["CREATE CONSTRAINT a IF NOT EXISTS", "CREATE INDEX b"]


def test_apply_cypher_file_skips_empty_statements(tmp_path):
    """T2: empty statements (after comment-stripping) are skipped."""
    f = _w(
        tmp_path, "x.cypher", ";;\n// just a comment\n;\nCREATE CONSTRAINT a IF NOT EXISTS;\n;\n"
    )
    drv = _Driver(_Session())
    result = apply_cypher_file(drv, f)
    assert result.statements_run == 1
    assert result.errors == []
    assert drv._s.queries == ["CREATE CONSTRAINT a IF NOT EXISTS"]


def test_apply_cypher_file_semicolon_inside_comment_does_not_orphan_text(tmp_path):
    """T3: a ';' inside a // comment does not split trailing non-comment text."""
    f = _w(
        tmp_path,
        "x.cypher",
        "// note: use foo;bar; not foo\nCREATE CONSTRAINT a IF NOT EXISTS;\nCREATE INDEX b;\n",
    )
    drv = _Driver(_Session())
    result = apply_cypher_file(drv, f)
    assert result.statements_run == 2
    assert drv._s.queries == ["CREATE CONSTRAINT a IF NOT EXISTS", "CREATE INDEX b"]


def test_apply_cypher_file_reports_driver_error_with_context(tmp_path):
    """T4: when statement N raises, ApplyResult.errors captures it; prior statements have run."""
    f = _w(
        tmp_path,
        "x.cypher",
        "CREATE CONSTRAINT a IF NOT EXISTS;\nCREATE INDEX b;\nCREATE INDEX c;\n",
    )
    boom = RuntimeError("schema violation")
    drv = _Driver(_Session(fail_on=2, exc=boom))
    with pytest.raises(CypherStatementError) as exc_info:
        apply_cypher_file(drv, f)
    err = exc_info.value.errors[0]
    assert err.index == 2
    assert "CREATE INDEX b" in err.statement
    assert err.exception is boom
    # Statement 1 already executed; no roll-back via the helper.
    assert drv._s.queries == ["CREATE CONSTRAINT a IF NOT EXISTS", "CREATE INDEX b"]
