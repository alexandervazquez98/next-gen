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

import re
import sys
import textwrap
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


def _patch_database_client_error(monkeypatch):
    """Patch ``database._CLIENT_ERROR_CLASS`` to a real class and return the module.

    The conftest stubs ``sys.modules['neo4j.exceptions']`` to a MagicMock
    so the production ``database._CLIENT_ERROR_CLASS`` ends up a MagicMock
    attribute — making ``isinstance(error, ClientError)`` checks unreliable.
    This helper monkeypatches the captured reference on the live
    ``database`` module to a real exception class so the predicate behaves
    like production. Returns the ``database`` module so callers can call
    ``verify_cypher_smoke``.

    Critically, this helper does NOT pop ``database`` from ``sys.modules``,
    swap in a fake ``neo4j`` package, or import ``services.event_service``
    at module load — those reload strategies either left downstream
    ``services.*`` / ``routers.*`` modules holding stale
    ``from database import get_db`` bindings (broke 23 unrelated tests
    patching ``database.driver``) or triggered ``postgres_db.load_dotenv``
    side-effects that polluted os.environ with ``COOKIE_SECURE=false``
    from the repo .env file (broke the auth cookie security tests).
    """
    import database

    monkeypatch.setattr(database, "_CLIENT_ERROR_CLASS", _FakeClientError)
    return database


@pytest.fixture
def _restore_neo4j_modules():
    """No-op safety net for tests that previously needed ``sys.modules`` rollback.

    Earlier revisions of this file reloaded ``sys.modules['database']`` and
    swapped in a fake ``neo4j`` package so the captured
    ``_CLIENT_ERROR_CLASS`` resolved to a real class. That reload leaked
    stale ``from database import get_db`` bindings into downstream
    ``services.*`` / ``routers.*`` modules and broke 23 unrelated tests in
    ``test_routers_metrics_events.py``,
    ``test_topology_relationships.py``, and ``test_topology_tunnel_health.py``.

    ``_patch_database_client_error`` (the new helper) does not touch
    ``sys.modules``; it monkeypatches ``database._CLIENT_ERROR_CLASS`` in
    place. This fixture is kept for backward compatibility with existing
    test signatures but no longer needs to perform any restore work.
    """
    yield


@pytest.fixture
def database_module(monkeypatch, _restore_neo4j_modules):
    """Provide the ``database`` module with ``_CLIENT_ERROR_CLASS`` set to a real class."""
    monkeypatch.delenv("DISABLE_NEO4J_SMOKE", raising=False)
    return _patch_database_client_error(monkeypatch)


@pytest.fixture
def database_module_disabled(monkeypatch, _restore_neo4j_modules):
    """Provide the ``database`` module with ``DISABLE_NEO4J_SMOKE=true``."""
    monkeypatch.setenv("DISABLE_NEO4J_SMOKE", "true")
    return _patch_database_client_error(monkeypatch)


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
