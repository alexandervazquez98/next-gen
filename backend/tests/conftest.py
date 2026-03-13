"""
conftest.py — backend/tests

Stubs out heavy infrastructure modules (database drivers, Neo4j, etc.) so that
unit tests can import service modules without a live database.

This file is loaded by pytest BEFORE any test module is imported, which means
the stubs are in sys.modules before any module-level code tries to use them.
"""

import sys
from unittest.mock import MagicMock

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
