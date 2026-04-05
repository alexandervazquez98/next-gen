# backend/tests/conftest.py
"""
conftest.py — backend/tests

Stubs out heavy infrastructure modules (database drivers, Neo4j, etc.) so that
unit tests can import service modules without a live database.

This file is loaded by pytest BEFORE any test module is imported, which means
the stubs are in sys.modules before any module-level code tries to use them.

Also provides shared pytest fixtures and configuration for NEX-GEN backend tests:
- Base fixtures for auth/security testing
- Mock Neo4j driver/session fixtures for DB-dependent tests
- Test constants (SECRET_KEY override, etc.)
- Helpers for creating test users/tokens without hitting the DB
"""

import sys
import os
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# ── Stub psycopg2 so postgres_db.py can be imported without a real Postgres ──
psycopg2_stub = MagicMock()
psycopg2_stub.extensions = MagicMock()
sys.modules["psycopg2"] = psycopg2_stub
sys.modules["psycopg2.extensions"] = psycopg2_stub.extensions

# ── Stub neo4j so topology_repo.py can be imported without a real Neo4j ──────
neo4j_stub = MagicMock()
sys.modules["neo4j"] = neo4j_stub
sys.modules["neo4j.exceptions"] = MagicMock()

# ── Stub pysnmp (used by snmp_service) ───────────────────────────────────────
for mod in [
    "pysnmp",
    "pysnmp.hlapi",
    "pysnmp.hlapi.asyncio",
]:
    sys.modules[mod] = MagicMock()

# Ensure backend root is on the import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TEST_SECRET_KEY = "test-secret-key-for-unit-tests"
TEST_ALGORITHM = "HS256"

# ---------------------------------------------------------------------------
# Fixtures — pure logic, no DB
# ---------------------------------------------------------------------------


@pytest.fixture
def test_secret_key() -> str:
    """Override SECRET_KEY for token creation/decoding in tests."""
    return TEST_SECRET_KEY


@pytest.fixture
def sample_user_data() -> dict:
    """Minimal user payload for tests."""
    return {
        "username": "testuser",
        "role": "OPERATOR",
        "permissions": ["EVENT_VIEW", "CI_VIEW"],
        "allowed_locations": ["HQ-Madrid"],
        "allowed_ci_types": ["router", "switch"],
        "phone": "+34600000000",
        "email": "test@example.com",
        "disabled": False,
        "force_password_change": False,
    }


@pytest.fixture
def sample_admin_data() -> dict:
    """Admin user payload for permission tests."""
    return {
        "username": "adminuser",
        "role": "ADMIN",
        "permissions": [],
        "allowed_locations": [],
        "allowed_ci_types": None,
        "disabled": False,
        "force_password_change": False,
    }


@pytest.fixture
def sample_disabled_user_data() -> dict:
    """Disabled user payload for activation tests."""
    return {
        "username": "disableduser",
        "role": "VIEWER",
        "permissions": [],
        "allowed_locations": [],
        "allowed_ci_types": None,
        "disabled": True,
        "force_password_change": False,
    }


@pytest.fixture
def plain_password() -> str:
    """A known plain-text password for hashing tests."""
    return "TestP@ss123!"


@pytest.fixture
def hashed_password(plain_password: str) -> str:
    """Pre-hashed password using the project's security utilities."""
    from utils.security import get_password_hash

    return get_password_hash(plain_password)


@pytest.fixture
def create_test_token(test_secret_key: str) -> callable:
    """
    Factory fixture that returns a function to create JWT tokens
    using the test secret key (avoids DB dependency).
    """
    from jose import jwt

    def _create_token(
        username: str,
        role: str = "VIEWER",
        expires_delta: timedelta | None = None,
    ) -> str:
        to_encode = {"sub": username, "role": role}
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=15)
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, test_secret_key, algorithm=TEST_ALGORITHM)

    return _create_token


@pytest.fixture
def valid_test_token(create_test_token: callable) -> str:
    """A valid JWT token with default expiry."""
    return create_test_token("testuser", "OPERATOR")


# ---------------------------------------------------------------------------
# Fixtures — Mock Neo4j Database
# ---------------------------------------------------------------------------


class MockNeo4jResult:
    """Helper to simulate Neo4j query results in tests."""

    def __init__(self, records: List[Dict[str, Any]]):
        self._records = records
        self._index = 0

    def __iter__(self):
        self._index = 0
        return self

    def __next__(self):
        if self._index >= len(self._records):
            raise StopIteration
        record = self._records[self._index]
        self._index += 1
        return MockNeo4jRecord(record)

    def single(self):
        """Return the first record as a MockNeo4jRecord, or None."""
        if self._records:
            return MockNeo4jRecord(self._records[0])
        return None


class MockNeo4jRecord:
    """Simulates a Neo4j record dict-like access."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def __getitem__(self, key):
        return self._data.get(key)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __contains__(self, key):
        return key in self._data


class MockNeo4jSession:
    """Simulates a Neo4j session with controllable query responses."""

    def __init__(self):
        self.queries: List[Dict[str, Any]] = []
        self._response_map: Dict[str, List[Dict[str, Any]]] = {}
        self._default_response: List[Dict[str, Any]] = []

    def set_response(self, query_contains: str, records: List[Dict[str, Any]]):
        """Set a canned response for queries containing the given substring."""
        self._response_map[query_contains.lower()] = records

    def set_default_response(self, records: List[Dict[str, Any]]):
        """Set a fallback response for any unmatched query."""
        self._default_response = records

    def run(self, query: str, **params):
        """Capture the query and return the matching canned response."""
        self.queries.append({"query": query, "params": params})
        query_lower = query.lower()
        for key, records in self._response_map.items():
            if key in query_lower:
                return MockNeo4jResult(records)
        return MockNeo4jResult(self._default_response)

    def begin_transaction(self):
        """Return a separate transaction object to properly test atomicity."""
        return MockNeo4jTransaction(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockNeo4jTransaction:
    """Simulates a Neo4j explicit transaction with commit/rollback tracking."""

    def __init__(self, session: MockNeo4jSession):
        self._session = session
        self.committed = False
        self.rolled_back = False

    def run(self, query: str, **params):
        """Delegate query execution to the parent session for capture."""
        return self._session.run(query, **params)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *args):
        if exc_type:
            self.rolled_back = True
        else:
            self.committed = True
        return False  # don't suppress exceptions


class MockNeo4jDriver:
    """Simulates a Neo4j driver that yields mock sessions."""

    def __init__(self):
        self.session = MagicMock()
        self._mock_session = MockNeo4jSession()
        self.session.return_value = self._mock_session

    @property
    def mock_session(self) -> MockNeo4jSession:
        return self._mock_session


@pytest.fixture
def mock_neo4j_driver():
    """
    Provide a mock Neo4j driver that can be configured with canned responses.

    Patches the 'driver' global in the database module so that get_db()
    returns the mock. Also patches 'verify_connection' to prevent real
    connection attempts at import time.

    Usage:
        def test_something(mock_neo4j_driver):
            mock_neo4j_driver.mock_session.set_response(
                "match (m:metricdef)",
                [{"m": {"id": "cpu-load", "protocol": "SNMP"}}]
            )
            # Call code that uses database.get_db()
    """
    driver = MockNeo4jDriver()

    # Patch at the database module level (where driver global lives)
    with patch("database.driver", driver):
        with patch("database.verify_connection", return_value=None):
            yield driver


@pytest.fixture
def mock_neo4j_session(mock_neo4j_driver):
    """Convenience fixture that gives direct access to the mock session."""
    return mock_neo4j_driver.mock_session


# ---------------------------------------------------------------------------
# Fixtures — Test Data Factories (Metric & Event domain)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_metric_def() -> dict:
    """Standard MetricDef payload for tests."""
    return {
        "id": "cpu-load",
        "protocol": "SNMP",
        "oid": "1.3.6.1.2.1.25.3.3.1.2",
        "warning": 80.0,
        "critical": 95.0,
        "dataType": "INTEGER",
        "unit": "%",
        "description": "CPU Load percentage",
        "criticality": 2,
        "applicable_to": {
            "brands": ["cisco"],
            "models": [],
            "layers": [],
            "names": [],
            "excluded_names": [],
        },
    }


@pytest.fixture
def sample_icmp_metric() -> dict:
    """ICMP metric definition for tests."""
    return {
        "id": "PING-Router-01",
        "protocol": "ICMP",
        "oid": "ICMP",
        "warning": 0,
        "critical": 0,
        "description": "Monitoreo via ping ICMP",
        "applicable_to": {"names": ["Router-01"]},
    }


@pytest.fixture
def sample_ci_node() -> dict:
    """Standard CI node payload for tests."""
    return {
        "id": "ci-001",
        "label": "Router-01",
        "type": "router",
        "status": "OK",
        "ip": "192.168.1.1",
        "brand": "Cisco",
        "model": "ASR-1000",
        "name": "Router-01",
        "layer": "router",
        "owner": "NetOps",
        "locationName": "Data Center A",
        "pollingInterval": 60,
        "snmp": {"version": "v2c", "readCommunity": "public"},
        "metrics": [],
        "metadata": {},
    }


@pytest.fixture
def sample_event() -> dict:
    """Standard event payload for tests."""
    return {
        "id": "evt-001",
        "ci_id": "ci-001",
        "metric_id": "cpu-load",
        "severity": "CRITICAL",
        "status": "OPEN",
        "value": 97.5,
        "message": "CPU Load exceeded critical threshold",
        "created_at": datetime.utcnow(),
    }


@pytest.fixture
def sample_admin_user():
    """Admin User model instance for service-layer tests."""
    from models.user import User

    return User(
        username="admin",
        role="ADMIN",
        permissions=[],
        allowed_locations=[],
    )


@pytest.fixture
def sample_operator_user():
    """Operator User model instance for service-layer tests."""
    from models.user import User

    return User(
        username="operator",
        role="OPERATOR",
        permissions=["EVENT_VIEW", "CI_VIEW", "CI_EDIT"],
        allowed_locations=["HQ-Madrid"],
    )
