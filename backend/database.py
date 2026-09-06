import os

from neo4j import GraphDatabase

# load_dotenv()  <-- Eliminado para que Docker mande

URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687").strip("'\"")
USER = os.getenv("NEO4J_USER", "neo4j").strip("'\"")
PASSWORD = os.getenv("NEO4J_PASSWORD", "").strip("'\"")

if not USER or not PASSWORD:
    print(f"CRITICAL: Neo4j credentials missing in environment! USER={USER}")
else:
    # Mostramos solo el primer y último caracter de la pass para debuggear sin quemarla
    masked_pass = f"{PASSWORD[0]}...{PASSWORD[-1]}" if len(PASSWORD) > 2 else "***"
    print(f"DEBUG: Attempting Neo4j connection to {URI} with user '{USER}' and pass {masked_pass} (len: {len(PASSWORD)})")

AUTH = (USER, PASSWORD)
driver = GraphDatabase.driver(URI, auth=AUTH)

# Capture the real ``ClientError`` class at module load so the smoke can
# ``isinstance``-check it without re-importing and so tests can monkeypatch
# the captured reference (see ``backend/tests/test_neo4j_smoke.py``).
# Issue #459: the smoke must fail loudly on CypherSyntaxError so a
# regression like ``ORDER BY ... ASC NULLS LAST`` aborts cold start instead
# of being served to operators as silent stale data.
import neo4j.exceptions as _neo4j_exceptions  # noqa: E402

_CLIENT_ERROR_CLASS = _neo4j_exceptions.ClientError

# Module-level toggle for tests and offline environments. Set to a truthy
# value (``true`` / ``1``, case-insensitive) to short-circuit the smoke at
# startup; the helper still raises on ``ClientError`` when the flag is off.
_DISABLE_NEO4J_SMOKE_ENV = "DISABLE_NEO4J_SMOKE"


def _is_truthy(value: str | None) -> bool:
    """Return True for the canonical truthy string values.

    Mirrors the loose convention used elsewhere in the project (e.g.
    ``DISABLE_BACKEND_COLLECTOR`` in ``docker-compose.yml``). Empty string
    and ``None`` are falsy.
    """
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_db():
    if not driver:
        # Re-connect if needed logic here or handled by driver
        pass
    return driver

def close_db():
    if driver:
        driver.close()

import time  # noqa: E402


def verify_connection(max_retries: int = 30, retry_delay: float = 2.0) -> None:
    for i in range(max_retries):
        try:
            driver.verify_connectivity()
            print("Neo4j Connection Verified")
            return
        except Exception as e:
            print(f"Neo4j Connection Failed (Attempt {i+1}/{max_retries}): {e}")
            if i < max_retries - 1 and retry_delay > 0:
                time.sleep(retry_delay)

    print("Neo4j Connection Failed after max retries")
    raise Exception("Could not connect to Neo4j Database")


def verify_cypher_smoke(driver_to_check=None) -> bool:
    """Run a minimal ``RETURN 1 AS ok`` probe against the live driver.

    Wired ONLY into ``main.startup_event`` (issue #459 / spec
    ``neo4j-cypher-compatibility``). MUST NOT live inside
    ``verify_connection()`` because that function is also called from the
    ``/api/system/status`` polling path; re-running the smoke every poll
    would multiply DB traffic by ~20x.

    Returns
    -------
    bool
        ``True`` when the probe ran successfully. ``False`` when the
        ``DISABLE_NEO4J_SMOKE`` kill-switch is set (smoke skipped).

    Raises
    ------
    neo4j.exceptions.ClientError
        Propagated verbatim so the startup hook can abort cold start.
    """
    if _is_truthy(os.getenv(_DISABLE_NEO4J_SMOKE_ENV)):
        # Kill-switch: tests with stubbed drivers (and offline local dev)
        # need the backend to boot without issuing a real Cypher round-trip.
        return False

    target_driver = driver_to_check if driver_to_check is not None else driver
    with target_driver.session() as session:
        # Single row, single column. ``LIMIT 1`` semantics are irrelevant
        # for ``RETURN 1`` but the ``AS ok`` alias documents intent.
        result = session.run("RETURN 1 AS ok").single()
        if result is None:
            raise RuntimeError("Neo4j smoke probe returned no row for RETURN 1")
        # Defensive read — the canonical column is ``ok``; fall back to
        # the first value so a future refactor of the probe shape still
        # produces a clean success.
        ok_value = result.get("ok") if hasattr(result, "get") else None
        if ok_value is None and hasattr(result, "__iter__"):
            try:
                ok_value = next(iter(result))
            except StopIteration:
                ok_value = None
        if ok_value != 1:
            raise RuntimeError(
                f"Neo4j smoke probe unexpected value: ok={ok_value!r}"
            )
    return True
