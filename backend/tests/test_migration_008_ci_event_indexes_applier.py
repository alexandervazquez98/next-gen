"""Tests for the 008_ci_event_indexes applier — feat-523-ci-event-neo4j-indexes.

Verifies:
- The applier module exists at the correct path.
- It exposes the expected public API (apply_ci_event_indexes, main).
- The applier references the correct migration file.
- Running as a script exits non-zero when Neo4j is unreachable.
- _extract_cypher_statements correctly handles semicolons inside // comments (no fragment leaks).
- The runbook and script docstring document the docker compose exec form.

Pure file-level checks; the subprocess test covers the exit-code path.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations" / "008_ci_event_indexes.cypher"
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "migrate_ci_event_indexes.py"
RUNBOOK_PATH = Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "008-ci-event-indexes.md"


def test_applier_script_exists():
    """The applier MUST exist at backend/scripts/migrate_ci_event_indexes.py."""
    assert SCRIPT_PATH.exists(), f"Applier missing: {SCRIPT_PATH}"
    assert SCRIPT_PATH.name == "migrate_ci_event_indexes.py"


def test_applier_exposes_apply_function():
    """The applier MUST expose apply_ci_event_indexes(driver=None)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("migrate_ci_event_indexes", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(
        module, "apply_ci_event_indexes"
    ), "apply_ci_event_indexes function not found in migrate_ci_event_indexes"


def test_applier_exposes_main():
    """The applier MUST expose main() for CLI invocation."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("migrate_ci_event_indexes", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "main"), "main() not found in migrate_ci_event_indexes"


def test_applier_references_correct_migration_file():
    """The applier MUST read 008_ci_event_indexes.cypher."""
    body = SCRIPT_PATH.read_text(encoding="utf-8")
    assert (
        "008_ci_event_indexes.cypher" in body
    ), "Applier must reference the migration file 008_ci_event_indexes.cypher"


def test_script_exits_nonzero_without_neo4j():
    """Running the script without Neo4j MUST exit non-zero (preflight or connection error)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        env={**subprocess.os.environ.copy(), "NEO4J_URI": "bolt://localhost:7777"},
        timeout=15,
    )
    assert result.returncode != 0, (
        f"Expected non-zero exit when Neo4j is unreachable, got {result.returncode}. "
        f"stdout: {result.stdout!r}  stderr: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Regression tests for Defect 1 — no comment-prose fragment leaks
# ---------------------------------------------------------------------------


def test_real_migration_yields_exactly_five_statements():
    """Parsing the real migration file yields exactly 5 statements.

    Regression: splitting on ';' before dropping // lines orphans trailing comment
    prose that contains a semicolon, producing junk statements.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("migrate_ci_event_indexes", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    content = MIGRATION_PATH.read_text(encoding="utf-8")
    statements = module._extract_cypher_statements(content)

    assert (
        len(statements) == 5
    ), f"Expected exactly 5 statements, got {len(statements)}: {statements}"


def test_real_migration_statements_all_start_with_cypher_keywords():
    """Every statement from the real migration must start with CREATE (no comment leaks).

    The header comment contains semicolons. If the parser splits before stripping
    comments, those semicolons produce fragment statements that do NOT start with
    a Cypher keyword.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("migrate_ci_event_indexes", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    content = MIGRATION_PATH.read_text(encoding="utf-8")
    statements = module._extract_cypher_statements(content)

    cypher_keywords = ("CREATE", "MATCH", "SHOW", "DROP", "USE", "CALL", "RETURN")
    for stmt in statements:
        assert stmt.startswith(
            cypher_keywords
        ), f"Statement does not start with a Cypher keyword: {stmt!r}"


def test_parser_ignores_semicolons_inside_double_slash_comments():
    """A synthetic migration with semicolons inside // comments produces zero statements.

    Guards the parser independently of the current migration file's contents.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("migrate_ci_event_indexes", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    synthetic = """\
// This is a comment; with a semicolon inside it
// Another line; still part of the comment
// Final line; with semicolon
"""
    statements = module._extract_cypher_statements(synthetic)
    assert (
        len(statements) == 0
    ), f"Expected 0 statements from comment-only input, got {len(statements)}: {statements}"


def test_parser_handles_mixed_comments_and_real_statements():
    """Semicolons inside // comments do not break real CREATE statements."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("migrate_ci_event_indexes", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Semicolons in comment lines + two real statements
    synthetic = """\
// Header; comment with semicolon
// Another; semicolon in comment
CREATE INDEX foo IF NOT EXISTS FOR (n:Label) ON (n.prop);

// Mid comment; split on semicolon here too
CREATE INDEX bar IF NOT EXISTS FOR (m:Other) ON (m.key);
"""
    statements = module._extract_cypher_statements(synthetic)
    assert len(statements) == 2, f"Expected 2 statements, got {len(statements)}: {statements}"
    assert statements[0].startswith("CREATE INDEX foo")
    assert statements[1].startswith("CREATE INDEX bar")


# ---------------------------------------------------------------------------
# Regression tests for Defect 2 — runbook must document docker compose exec form
# ---------------------------------------------------------------------------


def test_runbook_contains_docker_compose_exec_form():
    """The runbook's apply command must use docker compose exec, not host-side python."""
    body = RUNBOOK_PATH.read_text(encoding="utf-8")
    assert "docker compose exec -T backend python scripts/" in body, (
        "Runbook must document 'docker compose exec -T backend python scripts/' form; "
        "host-side 'python backend/scripts/...' will fail outside the compose network."
    )


def test_runbook_does_not_document_host_side_python_form():
    """The runbook must NOT document the host-side python backend/scripts/ form."""
    body = RUNBOOK_PATH.read_text(encoding="utf-8")
    # The host-side form is wrong; the script docstring currently has it — that must be fixed too
    host_form = "python backend/scripts/migrate_ci_event_indexes.py"
    assert host_form not in body, (
        "Runbook must not document 'python backend/scripts/migrate_ci_event_indexes.py'; "
        "use 'docker compose exec -T backend python scripts/migrate_ci_event_indexes.py' instead."
    )


def test_script_docstring_contains_docker_compose_exec_form():
    """The script's module docstring must document docker compose exec, not host python."""
    body = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "docker compose exec -T backend python scripts/" in body, (
        "Script docstring must document 'docker compose exec -T backend python scripts/' form; "
        "host-side 'python backend/scripts/...' will fail outside the compose network."
    )
