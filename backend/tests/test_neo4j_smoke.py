# backend/tests/test_neo4j_smoke.py
"""Unit tests for ``backend/database.py::verify_cypher_smoke`` and the
``NULLS FIRST`` / ``NULLS LAST`` regression scan.

Strict TDD (tasks.md §Phase 1): this file lands BEFORE the helper. The
helper + smoke wiring live in Phase 2.

Coverage:

- ``TestVerifyCypherSmoke``
    - ``test_runs_round_trip`` — successful ``RETURN 1`` returns truthy.
    - ``test_raises_on_client_error`` — a ``ClientError`` propagates so
      startup fails loudly.
    - ``test_disable_flag_skips`` — ``DISABLE_NEO4J_SMOKE=true`` short-
      circuits the call (returns False without issuing a query).

- ``TestNullsRegressionScan``
    - ``test_scan_detects_nulls_last`` — a fixture file containing
      ``NULLS LAST`` under ``backend/services/`` is rejected.
    - ``test_scan_excludes_tests`` — files under ``backend/tests/`` are
      ignored so negative regression assertions in tests do not break CI.
    - ``test_scan_passes_clean_tree`` — when no production file contains
      the pattern, the scanner returns an empty result.
"""

from __future__ import annotations

import importlib
import re
import sys
import textwrap
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Regression scanner — exported at module level so CI / other test
# classes can import it without going through ``database``. The scan is
# part of the public test surface: it is invoked from the test runner
# (the test cases below) and is small enough to live alongside its
# coverage.
# ---------------------------------------------------------------------------

# Pattern matches the canonical Cypher grammar reject — the explicit
# ``NULLS FIRST`` / ``NULLS LAST`` keyword combination. Case-insensitive so
# a sloppy reintroduction (``nulls last``) is also caught. Word boundary on
# the trailing token prevents partial-match noise (e.g. ``NULLS_LAST`` as
# part of an unrelated identifier).
NULLS_ORDERING_PATTERN = re.compile(
    r"NULLS\s+(FIRST|LAST)\b",
    re.IGNORECASE,
)


def scan_nulls_first_last(*roots: Path) -> list[dict[str, object]]:
    """Walk ``roots`` for ``.py`` files containing ``NULLS FIRST/LAST``.

    Returns a list of offender dicts ``{"path": str, "line": int, "match": str}``.
    An empty list means the source tree is clean.

    Excludes ``backend/tests/`` automatically so negative regression
    assertions in tests do not trip the scan. The exclusion is enforced
    by inspecting each candidate file's path components: any ``tests``
    directory under the scan root is skipped. This matches the spec
    (``neo4j-cypher-compatibility`` "CI Regression Scan for
    ``NULLS FIRST``/``NULLS LAST`` Syntax").
    """
    offenders: list[dict[str, object]] = []
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.rglob("*.py"):
            # Skip test fixtures under any ``tests`` directory in the scan
            # tree. The production scan walks ``backend/services/`` and
            # ``backend/engines/`` so this excludes e.g.
            # ``backend/services/tests/...`` (defensive, not expected).
            if any(part == "tests" for part in candidate.parts):
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                match = NULLS_ORDERING_PATTERN.search(line)
                if match:
                    offenders.append(
                        {
                            "path": str(candidate),
                            "line": line_no,
                            "match": match.group(0),
                        }
                    )
    return offenders


# ---------------------------------------------------------------------------
# Stub heavy modules BEFORE importing database (same pattern as conftest.py).
# ---------------------------------------------------------------------------

for mod in ["psycopg2", "psycopg2.extensions"]:
    sys.modules.setdefault(mod, MagicMock())


class _FakeClientError(Exception):
    """Real exception class standing in for ``neo4j.exceptions.ClientError``.

    The conftest stubs ``sys.modules['neo4j.exceptions']`` to a MagicMock so
    ``ClientError`` is a MagicMock instance, not a real class — making
    ``isinstance(error, ClientError)`` checks unreliable. The helper
    captures the class at module load; tests patch the captured reference
    on the live module to this real class so the predicate behaves as it
    would in production.
    """

    def __init__(self, message: str = "", code: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code


def _load_database_module():
    """Reload database with a stubbed neo4j so we can patch the captured ClientError."""
    sys.modules.pop("database", None)
    # Build a fake neo4j module whose ``exceptions.ClientError`` is a real
    # class we can subclass + raise from tests. Otherwise the database
    # module captures a MagicMock attribute and isinstance checks fail.
    fake_neo4j = types.ModuleType("neo4j")
    fake_exc = types.ModuleType("neo4j.exceptions")
    fake_exc.ClientError = _FakeClientError
    fake_neo4j.exceptions = fake_exc
    sys.modules["neo4j"] = fake_neo4j
    sys.modules["neo4j.exceptions"] = fake_exc
    # Also need a fake GraphDatabase.driver so database module init succeeds.
    fake_neo4j.GraphDatabase = types.SimpleNamespace(driver=MagicMock(return_value=MagicMock()))
    return importlib.import_module("database")


@pytest.fixture
def _restore_neo4j_modules():
    """Save and restore ``sys.modules['neo4j*']`` around test fixtures.

    The ``_load_database_module`` helper swaps in a synthetic ``neo4j``
    module that exposes a real ``ClientError`` class. Without this
    fixture, the fake persists across the test session and breaks other
    test files that import the real ``neo4j`` package (e.g.
    ``from neo4j import Query as Neo4jQuery`` in ``main.py``).
    """
    saved_neo4j = sys.modules.get("neo4j")
    saved_neo4j_exc = sys.modules.get("neo4j.exceptions")
    try:
        yield
    finally:
        if saved_neo4j is None:
            sys.modules.pop("neo4j", None)
        else:
            sys.modules["neo4j"] = saved_neo4j
        if saved_neo4j_exc is None:
            sys.modules.pop("neo4j.exceptions", None)
        else:
            sys.modules["neo4j.exceptions"] = saved_neo4j_exc
        # Also drop the freshly-loaded ``database`` module so the next
        # test gets a clean re-import off the restored real ``neo4j``.
        sys.modules.pop("database", None)


@pytest.fixture
def database_module(monkeypatch, _restore_neo4j_modules):
    """Provide a freshly-loaded database module whose ClientError is a real class."""
    # Strip DISABLE_NEO4J_SMOKE so tests default to "enabled".
    monkeypatch.delenv("DISABLE_NEO4J_SMOKE", raising=False)
    return _load_database_module()


@pytest.fixture
def database_module_disabled(monkeypatch, _restore_neo4j_modules):
    """Provide a freshly-loaded database module with DISABLE_NEO4J_SMOKE=true."""
    monkeypatch.setenv("DISABLE_NEO4J_SMOKE", "true")
    return _load_database_module()


# ---------------------------------------------------------------------------
# Tests for ``verify_cypher_smoke``
# ---------------------------------------------------------------------------


class TestVerifyCypherSmoke:
    """RED -> GREEN: the startup smoke must validate Cypher, fail loudly on
    ``ClientError``, and respect the ``DISABLE_NEO4J_SMOKE`` kill-switch.
    """

    def test_runs_round_trip(self, database_module):
        """A healthy driver executes ``RETURN 1`` and the helper returns truthy."""
        driver = MagicMock()
        session = MagicMock()
        result = MagicMock()
        result.single.return_value = {"ok": 1}
        session.run.return_value = result
        driver.session.return_value.__enter__.return_value = session

        outcome = database_module.verify_cypher_smoke(driver)

        assert outcome is True, f"Healthy driver must report success; got {outcome!r}"
        # Ensure the smoke issued the canonical probe query.
        issued_queries = [call.args[0] for call in session.run.call_args_list]
        assert issued_queries, "verify_cypher_smoke must issue at least one Cypher query"
        assert any(
            "RETURN 1" in q for q in issued_queries
        ), f"Smoke probe must include ``RETURN 1``; got queries={issued_queries!r}"

    def test_raises_on_client_error(self, database_module):
        """A ClientError from the smoke MUST propagate so startup fails loudly."""
        driver = MagicMock()
        session = MagicMock()
        session.run.side_effect = _FakeClientError(
            message="Invalid input 'NULLS': expected ...",
            code="Neo.ClientError.Statement.SyntaxError",
        )
        driver.session.return_value.__enter__.return_value = session

        with pytest.raises(_FakeClientError) as exc_info:
            database_module.verify_cypher_smoke(driver)

        assert "Invalid input 'NULLS'" in str(exc_info.value), (
            f"Propagated exception must carry the original Cypher error; " f"got {exc_info.value!r}"
        )

    def test_disable_flag_skips(self, database_module_disabled):
        """``DISABLE_NEO4J_SMOKE=true`` short-circuits without issuing any query."""
        driver = MagicMock()

        outcome = database_module_disabled.verify_cypher_smoke(driver)

        # The kill-switch returns a sentinel falsy value (skip) — NOT True.
        assert outcome is False, f"Kill-switch must return a skip sentinel; got {outcome!r}"
        # And must NOT have opened any session.
        driver.session.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for the ``NULLS FIRST`` / ``NULLS LAST`` regression scanner
# ---------------------------------------------------------------------------


class TestNullsRegressionScan:
    """RED -> GREEN: the scanner walks production source, rejects the
    forbidden pattern, and ignores ``backend/tests/`` fixtures.
    """

    def _make_fake_module(self, tmp_path: Path, files: dict[str, str]):
        """Create a fake backend tree with ``files`` (relative path -> content).

        Mirrors the structure ``scan_nulls_first_last`` expects: a
        ``services/`` and ``engines/`` directory under the supplied root.
        Returns the root path.
        """
        root = tmp_path / "backend"
        (root / "services").mkdir(parents=True)
        (root / "engines").mkdir(parents=True)
        (root / "tests").mkdir(parents=True)
        for rel, content in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(textwrap.dedent(content))
        return root

    def test_scan_detects_nulls_last(self, tmp_path):
        """A production ``.py`` containing ``NULLS LAST`` is reported as offender."""
        from backend.tests import test_neo4j_smoke as scanner_module

        files = {
            "services/example.py": (
                """\
                QUERY = \"\"\"
                MATCH (n)
                ORDER BY n.created_at ASC NULLS LAST
                \"\"\"
                """
            ),
        }
        backend_root = self._make_fake_module(tmp_path, files)

        offenders = scanner_module.scan_nulls_first_last(
            backend_root / "services", backend_root / "engines"
        )

        assert offenders, (
            "Scanner MUST flag a service file containing ``NULLS LAST``; "
            f"got offenders={offenders!r}"
        )
        assert any(
            "services/example.py" in off["path"] for off in offenders
        ), f"Offender must reference services/example.py; got {offenders!r}"

    def test_scan_excludes_tests(self, tmp_path):
        """A test fixture containing ``NULLS FIRST`` does NOT fail the build."""
        from backend.tests import test_neo4j_smoke as scanner_module

        files = {
            "tests/test_negative_assertion.py": (
                """\
                # Regression fixture: this string MUST appear so the scanner
                # has something to test against. It MUST be ignored.
                FORBIDDEN = 'NULLS FIRST'
                """
            ),
        }
        backend_root = self._make_fake_module(tmp_path, files)

        offenders = scanner_module.scan_nulls_first_last(
            backend_root / "services", backend_root / "engines"
        )

        assert offenders == [], f"Test fixtures MUST be ignored; got offenders={offenders!r}"

    def test_scan_passes_clean_tree(self, tmp_path):
        """When no production file contains the pattern, scan returns empty."""
        from backend.tests import test_neo4j_smoke as scanner_module

        files = {
            "services/clean.py": (
                """\
                # No NULLS keyword here.
                QUERY = "MATCH (n) RETURN n"
                """
            ),
            "engines/worker.py": (
                """\
                # Uses ORDER BY but no NULLS clause.
                QUERY = "MATCH (n) RETURN n ORDER BY n.created_at ASC"
                """
            ),
        }
        backend_root = self._make_fake_module(tmp_path, files)

        offenders = scanner_module.scan_nulls_first_last(
            backend_root / "services", backend_root / "engines"
        )

        assert offenders == [], f"Clean source tree must scan clean; got offenders={offenders!r}"

    def test_scan_uses_nulls_first_or_last_regex(self):
        """The scanner regex MUST match both NULLS FIRST and NULLS LAST."""
        from backend.tests import test_neo4j_smoke as scanner_module

        # The regex MUST be a compiled pattern exposed for direct testing
        # so a broken regex trips immediately at import time.
        pattern = scanner_module.NULLS_ORDERING_PATTERN
        assert isinstance(pattern, re.Pattern)
        assert pattern.search("ORDER BY x ASC NULLS LAST")
        assert pattern.search("ORDER BY x DESC NULLS FIRST")
        assert not pattern.search("ORDER BY x ASC")
        # Case-insensitive so a sloppy reintroduction is also caught.
        assert pattern.search("order by x asc nulls last")
