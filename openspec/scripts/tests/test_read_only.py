"""Tests for the read-only invariant — AST scan + runtime guard (WU-6 / REQ-007 / AD-09 / AD-12).

The CLI MUST NOT issue any write operation against Neo4j. Two
defence layers enforce this:

1. Static AST scan: walks the module's string constants and rejects
   any literal that contains a write token
   (``WRITE|MERGE|CREATE|DELETE|SET|REMOVE|DETACH|DROP``).
2. Runtime guard: `_safe_session_run` asserts the same token set
   against the query string before calling `session.run`.
3. Import-time guard: `topology_repo` MUST NOT be imported
   anywhere in the module (defence against accidental write helpers
   slipping in).
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "cmdb_backfill_orphans.py"
)


class TestStaticAstScan:
    """T-018 / T-019: AST scan rejects any string constant containing a write token."""

    def test_module_has_no_write_token_string_constants(self):
        """The shipped module MUST NOT contain any literal that matches the write regex."""
        from openspec.scripts.cmdb_backfill_orphans import _check_read_only_ast

        # No exception → the shipped module is clean.
        _check_read_only_ast(MODULE_PATH)

    def test_module_with_merge_literal_rejected(self, tmp_path):
        """A fixture module containing ``MERGE (n)-[:REL]->(m)`` MUST be flagged."""
        from openspec.scripts.cmdb_backfill_orphans import _check_read_only_ast

        fixture = tmp_path / "fixture_with_merge.py"
        fixture.write_text(
            textwrap.dedent(
                """\
                def fake_query():
                    return "MERGE (n)-[:REL]->(m)"
                """
            )
        )
        with pytest.raises(ValueError) as exc_info:
            _check_read_only_ast(fixture)
        assert "merge" in str(exc_info.value).lower()

    def test_module_with_create_literal_rejected(self, tmp_path):
        """A fixture with ``CREATE (n:CI)`` literal is rejected."""
        from openspec.scripts.cmdb_backfill_orphans import _check_read_only_ast

        fixture = tmp_path / "fixture_with_create.py"
        fixture.write_text(
            textwrap.dedent(
                """\
                def fake():
                    return "CREATE (n:CI {id: 1})"
                """
            )
        )
        with pytest.raises(ValueError):
            _check_read_only_ast(fixture)

    def test_module_with_delete_literal_rejected(self, tmp_path):
        from openspec.scripts.cmdb_backfill_orphans import _check_read_only_ast

        fixture = tmp_path / "fixture_with_delete.py"
        fixture.write_text(
            textwrap.dedent(
                """\
                def fake():
                    return "DELETE n"
                """
            )
        )
        with pytest.raises(ValueError):
            _check_read_only_ast(fixture)

    def test_module_with_set_literal_rejected(self, tmp_path):
        """``SET`` inside any string literal is rejected (even mid-string)."""
        from openspec.scripts.cmdb_backfill_orphans import _check_read_only_ast

        fixture = tmp_path / "fixture_with_set.py"
        fixture.write_text(
            textwrap.dedent(
                """\
                def fake():
                    return "MATCH (n) SET n.flag = 1"
                """
            )
        )
        with pytest.raises(ValueError):
            _check_read_only_ast(fixture)

    def test_module_with_remove_literal_rejected(self, tmp_path):
        from openspec.scripts.cmdb_backfill_orphans import _check_read_only_ast

        fixture = tmp_path / "fixture_with_remove.py"
        fixture.write_text(
            textwrap.dedent(
                """\
                def fake():
                    return "REMOVE n.flag"
                """
            )
        )
        with pytest.raises(ValueError):
            _check_read_only_ast(fixture)

    def test_module_with_detach_delete_literal_rejected(self, tmp_path):
        from openspec.scripts.cmdb_backfill_orphans import _check_read_only_ast

        fixture = tmp_path / "fixture_with_detach.py"
        fixture.write_text(
            textwrap.dedent(
                """\
                def fake():
                    return "DETACH DELETE n"
                """
            )
        )
        with pytest.raises(ValueError):
            _check_read_only_ast(fixture)

    def test_module_with_drop_literal_rejected(self, tmp_path):
        from openspec.scripts.cmdb_backfill_orphans import _check_read_only_ast

        fixture = tmp_path / "fixture_with_drop.py"
        fixture.write_text(
            textwrap.dedent(
                """\
                def fake():
                    return "DROP INDEX ci_id_idx"
                """
            )
        )
        with pytest.raises(ValueError):
            _check_read_only_ast(fixture)

    def test_module_with_no_write_tokens_passes(self, tmp_path):
        """A read-only-only module passes the scan."""
        from openspec.scripts.cmdb_backfill_orphans import _check_read_only_ast

        fixture = tmp_path / "fixture_clean.py"
        fixture.write_text(
            textwrap.dedent(
                """\
                def fake():
                    return "MATCH (n:CI) RETURN n.id AS ci_id"
                """
            )
        )
        # No exception → clean module.
        _check_read_only_ast(fixture)

    def test_write_token_regex_compiles(self):
        from openspec.scripts.cmdb_backfill_orphans import WRITE_TOKEN_RE

        assert WRITE_TOKEN_RE.search("MERGE (n)")
        assert WRITE_TOKEN_RE.search("create (n)")
        assert WRITE_TOKEN_RE.search("delete n")
        assert WRITE_TOKEN_RE.search("SET n.x = 1")
        assert WRITE_TOKEN_RE.search("REMOVE n.x")
        assert WRITE_TOKEN_RE.search("DETACH DELETE n")
        assert WRITE_TOKEN_RE.search("DROP INDEX foo")
        # Negative: read-only constructs are NOT flagged.
        assert not WRITE_TOKEN_RE.search("MATCH (n) RETURN n")
        assert not WRITE_TOKEN_RE.search("WHERE NOT EXISTS { MATCH (n)-[r]->(m) }")
        # ``write`` alone (English word in docstring) MUST NOT be flagged —
        # the regex is scoped to Cypher write keywords only.
        assert not WRITE_TOKEN_RE.search("No auto-write, no heuristics")
        assert not WRITE_TOKEN_RE.search("read-only invariant")


class TestSafeSessionRun:
    """Runtime guard: ``_safe_session_run`` blocks write queries before they hit the driver."""

    def test_match_passes_through(self):
        from openspec.scripts.cmdb_backfill_orphans import _safe_session_run

        class StubSession:
            def __init__(self):
                self.calls = []

            def run(self, query, **params):
                self.calls.append((query, params))
                return "RESULT"

        session = StubSession()
        result = _safe_session_run(session, "MATCH (n) RETURN n", cap=10)
        assert result == "RESULT"
        assert len(session.calls) == 1
        assert session.calls[0][0] == "MATCH (n) RETURN n"
        assert session.calls[0][1] == {"cap": 10}

    def test_merge_blocked(self):
        from openspec.scripts.cmdb_backfill_orphans import _safe_session_run

        class StubSession:
            def __init__(self):
                self.calls = []

            def run(self, query, **params):
                self.calls.append((query, params))
                return "RESULT"

        session = StubSession()
        with pytest.raises(ValueError) as exc_info:
            _safe_session_run(session, "MERGE (n)-[:REL]->(m)")
        assert "merge" in str(exc_info.value).lower()
        assert session.calls == [], "session.run must NOT be called for write queries"

    def test_create_blocked(self):
        from openspec.scripts.cmdb_backfill_orphans import _safe_session_run

        class StubSession:
            def run(self, query, **params):
                raise AssertionError("run must not be called for CREATE queries")

        with pytest.raises(ValueError):
            _safe_session_run(StubSession(), "CREATE (n:CI {id: 'x'})")

    def test_delete_blocked(self):
        from openspec.scripts.cmdb_backfill_orphans import _safe_session_run

        class StubSession:
            def run(self, query, **params):
                raise AssertionError("run must not be called for DELETE queries")

        with pytest.raises(ValueError):
            _safe_session_run(StubSession(), "MATCH (n) DELETE n")

    def test_set_blocked(self):
        from openspec.scripts.cmdb_backfill_orphans import _safe_session_run

        class StubSession:
            def run(self, query, **params):
                raise AssertionError("run must not be called for SET queries")

        with pytest.raises(ValueError):
            _safe_session_run(StubSession(), "MATCH (n) SET n.x = 1")

    def test_remove_blocked(self):
        from openspec.scripts.cmdb_backfill_orphans import _safe_session_run

        class StubSession:
            def run(self, query, **params):
                raise AssertionError("run must not be called for REMOVE queries")

        with pytest.raises(ValueError):
            _safe_session_run(StubSession(), "MATCH (n) REMOVE n.x")

    def test_detach_blocked(self):
        from openspec.scripts.cmdb_backfill_orphans import _safe_session_run

        class StubSession:
            def run(self, query, **params):
                raise AssertionError("run must not be called for DETACH queries")

        with pytest.raises(ValueError):
            _safe_session_run(StubSession(), "MATCH (n) DETACH DELETE n")

    def test_drop_blocked(self):
        from openspec.scripts.cmdb_backfill_orphans import _safe_session_run

        class StubSession:
            def run(self, query, **params):
                raise AssertionError("run must not be called for DROP queries")

        with pytest.raises(ValueError):
            _safe_session_run(StubSession(), "DROP INDEX ci_id_idx")

    def test_pass_through_returns_session_run_result(self):
        from openspec.scripts.cmdb_backfill_orphans import _safe_session_run

        sentinel = object()
        session = type("S", (), {"run": staticmethod(lambda q, **p: sentinel)})()
        assert _safe_session_run(session, "MATCH (n) RETURN n") is sentinel


class TestNoTopologyRepoImport:
    """T-020: ``topology_repo`` MUST NEVER be imported anywhere in the module."""

    def test_module_does_not_import_topology_repo(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "topology_repo" not in alias.name, (
                        f"topology_repo import at line {node.lineno}: {alias.name!r}"
                    )
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "topology_repo" not in module, (
                    f"topology_repo import from at line {node.lineno}: {module!r}"
                )
                for alias in node.names:
                    assert "topology_repo" not in alias.name, (
                        f"topology_repo name import at line {node.lineno}: {alias.name!r}"
                    )
