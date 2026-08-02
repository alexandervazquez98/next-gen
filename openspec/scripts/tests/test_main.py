"""Strict-TDD tests for the CLI wiring (WU-9).

Covers the four spec scenarios that touch the entry point:

- SCN-005: ``--output <path>`` writes a JSON file; stdout is empty.
- SCN-007: stderr audit line shape on success.
- SCN-008: ``--scope switch`` rejected before any driver call.
- SCN-009: missing Neo4j URI exits non-zero with no credentials.
"""

from __future__ import annotations

import io
import json
import sys
import types

import pytest


@pytest.fixture
def fake_session_module(monkeypatch):
    """Return a fake ``neo4j`` module whose ``GraphDatabase.driver`` returns
    a FakeSession capture object."""

    from openspec.scripts.tests.fake_neo4j import FakeSession

    captured: dict = {"session": None, "uri": None, "auth": None}

    class _Capture:
        def session(self, database=None):
            session = FakeSession(_orphan_rows())
            captured["session"] = session
            return session

    class GraphDatabase:
        @staticmethod
        def driver(uri, auth=None):
            captured["uri"] = uri
            captured["auth"] = auth
            return _Capture()

    module = types.ModuleType("neo4j")
    module.GraphDatabase = GraphDatabase
    monkeypatch.setitem(sys.modules, "neo4j", module)
    return captured


def _orphan_rows():
    return [
        {"ci_id": "ci-test-ap-orphan-001"},
        {"ci_id": "ci-test-ap-orphan-002"},
    ]


def test_parse_args_defaults_to_ap_and_default_rels():
    from openspec.scripts.cmdb_backfill_orphans import parse_args

    args = parse_args(
        ["--neo4j-uri", "bolt://db-host:7687"]
    )

    assert args.neo4j_uri == "bolt://db-host:7687"
    assert args.scope == "ap"
    assert args.relationship_types == ["DEPENDS_ON", "HOSTED_ON"]
    assert args.output is None
    assert args.format == "json"


def test_parse_args_accepts_custom_relationship_types():
    from openspec.scripts.cmdb_backfill_orphans import parse_args

    args = parse_args(
        [
            "--neo4j-uri",
            "bolt://db-host:7687",
            "--scope",
            "ap",
            "--relationship-types",
            "MANAGES",
            "RUNS_ON",
            "--output",
            "report.json",
        ]
    )

    assert args.relationship_types == ["MANAGES", "RUNS_ON"]
    assert args.output == "report.json"


def test_main_writes_output_file_scn005(tmp_path, fake_session_module, capsys):
    from openspec.scripts.cmdb_backfill_orphans import main

    target = tmp_path / "orphans.json"
    exit_code = main(
        [
            "--neo4j-uri",
            "bolt://db-host:7687",
            "--output",
            str(target),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["orphan_count"] == 2
    assert payload["ci_ids"][0] == "ci-test-ap-orphan-001"
    assert fake_session_module["uri"] == "bolt://db-host:7687"
    assert "ci-test-ap-orphan-001" in captured.err


def test_main_emits_audit_line_to_stderr_scn007(fake_session_module, capsys):
    from openspec.scripts.cmdb_backfill_orphans import main

    exit_code = main(["--neo4j-uri", "bolt://db-host:7687"])

    assert exit_code == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["orphan_count"] == 2

    stderr_lines = [line for line in captured.err.splitlines() if line]
    assert len(stderr_lines) == 1
    line = stderr_lines[0]
    assert "ts=" in line
    assert "query_hash=" in line
    assert "scope=ap" in line
    assert "rels=DEPENDS_ON,HOSTED_ON" in line
    assert "orphan_count=2" in line
    assert "exit=0" in line


def test_main_rejects_scope_switch_scn008(fake_session_module, capsys):
    from openspec.scripts.cmdb_backfill_orphans import main

    exit_code = main(
        ["--neo4j-uri", "bolt://db-host:7687", "--scope", "switch"]
    )

    assert exit_code != 0
    captured = capsys.readouterr()
    assert "invalid --scope switch" in captured.err
    assert "query_hash" not in captured.err
    assert fake_session_module["session"] is None


def test_main_missing_uri_exits_non_zero_without_credentials(capsys, monkeypatch):
    from openspec.scripts.cmdb_backfill_orphans import main

    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USER", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    exit_code = main([])

    assert exit_code != 0
    captured = capsys.readouterr()
    assert "--neo4j-uri" in captured.err
    assert "test-password" not in captured.err
    assert "test-password" not in captured.out


def test_main_emits_audit_line_for_missing_uri(capsys, monkeypatch):
    from openspec.scripts.cmdb_backfill_orphans import main

    monkeypatch.delenv("NEO4J_URI", raising=False)

    main([])

    captured = capsys.readouterr()
    audit_lines = [
        line
        for line in captured.err.splitlines()
        if "query_hash=" in line
    ]
    assert audit_lines, "missing-URI path still emits one audit line"
    assert "exit=1" in audit_lines[0]
