"""Tests for the 008_ci_event_indexes applier — feat-523-ci-event-neo4j-indexes.

Verifies:
- The applier module exists at the correct path.
- It exposes the expected public API (apply_ci_event_indexes, main).
- The applier references the correct migration file.
- Running as a script exits non-zero when Neo4j is unreachable.

Pure file-level checks; the subprocess test covers the exit-code path.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations" / "008_ci_event_indexes.cypher"
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "migrate_ci_event_indexes.py"


def test_applier_script_exists():
    """The applier MUST exist at backend/scripts/migrate_ci_event_indexes.py."""
    assert SCRIPT_PATH.exists(), f"Applier missing: {SCRIPT_PATH}"
    assert SCRIPT_PATH.name == "migrate_ci_event_indexes.py"


def test_applier_exposes_apply_function():
    """The applier MUST expose apply_ci_event_indexes(driver=None)."""
    # Import by file path without triggering database init.
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
