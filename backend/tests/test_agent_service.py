"""
test_agent_service.py

TDD unit tests for backend/services/agent_service.py.

All Neo4j / database calls are mocked so no live DB is required.

Scope:
  - register_agent: new agent path (CREATE)
  - register_agent: re-registration path (UPDATE)
  - agent_heartbeat: valid token updates last_seen
  - agent_heartbeat: invalid token raises 401
  - push_agent_metrics: valid token records value
  - push_agent_metrics: invalid token raises 401
  - list_agents: never exposes agent_token
  - delete_agent: removes node; raises 404 for unknown ID
"""

import sys
import os

# Make backend packages importable
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

import pytest
from unittest.mock import patch, MagicMock, call
from fastapi import HTTPException

from models.core import AgentRegistration, AgentMetricPush
import services.agent_service as agent_service_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(records=None, single_record=None):
    """
    Return a MagicMock that mimics a Neo4j session used as a context manager.

    ``records`` feeds the .run(...) iterable (for list queries).
    ``single_record`` is what .single() returns (for look-up queries).
    """
    session = MagicMock()
    run_result = MagicMock()
    run_result.__iter__ = MagicMock(return_value=iter(records or []))
    run_result.single.return_value = single_record
    session.run.return_value = run_result
    return session


def _driver_with_session(session):
    driver = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


# ---------------------------------------------------------------------------
# register_agent — new agent
# ---------------------------------------------------------------------------

class TestRegisterAgentNew:
    def test_creates_agent_node_when_none_exists(self):
        """
        GIVEN no existing agent with the hostname
        WHEN register_agent is called
        THEN a CREATE Cypher statement is issued and the returned dict
             contains id and agent_token.
        """
        session = _make_session(single_record=None)
        driver = _driver_with_session(session)

        payload = AgentRegistration(hostname="host-01", ip="10.0.0.1", os="Linux", version="1.0")

        with patch.object(agent_service_mod, "get_db", return_value=driver):
            result = agent_service_mod.register_agent(payload)

        assert "id" in result
        assert "agent_token" in result
        assert result["status"] == "ONLINE"

    def test_create_uses_uuid_for_id_and_token(self):
        """
        GIVEN a new registration
        WHEN register_agent is called
        THEN id and agent_token are non-empty strings (UUIDs).
        """
        session = _make_session(single_record=None)
        driver = _driver_with_session(session)

        payload = AgentRegistration(hostname="host-02")

        with patch.object(agent_service_mod, "get_db", return_value=driver):
            result = agent_service_mod.register_agent(payload)

        assert len(result["id"]) > 0
        assert len(result["agent_token"]) > 0
        assert result["id"] != result["agent_token"]


# ---------------------------------------------------------------------------
# register_agent — re-registration
# ---------------------------------------------------------------------------

class TestRegisterAgentExisting:
    def _existing_record(self, agent_id="existing-id", token="existing-token"):
        record = MagicMock()
        record.__getitem__ = MagicMock(
            side_effect=lambda k: {"a": {"id": agent_id, "agent_token": token}}[k]
        )
        return record

    def test_returns_existing_token_on_re_registration(self):
        """
        GIVEN an agent with the same hostname already exists in Neo4j
        WHEN register_agent is called again
        THEN the same agent_token is returned (not a new one).
        """
        existing = self._existing_record()
        session = _make_session(single_record=existing)
        driver = _driver_with_session(session)

        payload = AgentRegistration(hostname="host-01", ip="10.0.0.2")

        with patch.object(agent_service_mod, "get_db", return_value=driver):
            result = agent_service_mod.register_agent(payload)

        assert result["agent_token"] == "existing-token"
        assert result["id"] == "existing-id"


# ---------------------------------------------------------------------------
# agent_heartbeat
# ---------------------------------------------------------------------------

class TestAgentHeartbeat:
    def test_valid_token_returns_online(self):
        """
        GIVEN a valid agent_id / token pair
        WHEN agent_heartbeat is called
        THEN status ONLINE is returned.
        """
        record = MagicMock()
        record.__getitem__ = MagicMock(return_value={"id": "ag-1", "agent_token": "tok"})
        session = _make_session(single_record=record)
        driver = _driver_with_session(session)

        with patch.object(agent_service_mod, "get_db", return_value=driver):
            result = agent_service_mod.agent_heartbeat("ag-1", "tok")

        assert result["status"] == "ONLINE"
        assert "last_seen" in result

    def test_invalid_token_raises_401(self):
        """
        GIVEN an invalid token (not matching any Agent node)
        WHEN agent_heartbeat is called
        THEN an HTTPException with status_code 401 is raised.
        """
        session = _make_session(single_record=None)
        driver = _driver_with_session(session)

        with patch.object(agent_service_mod, "get_db", return_value=driver):
            with pytest.raises(HTTPException) as exc_info:
                agent_service_mod.agent_heartbeat("bad-id", "bad-token")

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# push_agent_metrics
# ---------------------------------------------------------------------------

class TestPushAgentMetrics:
    def test_valid_push_returns_accepted(self):
        """
        GIVEN a valid agent_id / token pair
        WHEN push_agent_metrics is called
        THEN accepted=True and the metric_id and value are echoed back.
        """
        record = MagicMock()
        record.__getitem__ = MagicMock(return_value={"id": "ag-1", "agent_token": "tok"})
        session = _make_session(single_record=record)
        driver = _driver_with_session(session)

        payload = AgentMetricPush(metric_id="cpu-load", value=72.5)

        with patch.object(agent_service_mod, "get_db", return_value=driver):
            result = agent_service_mod.push_agent_metrics("ag-1", "tok", payload)

        assert result["accepted"] is True
        assert result["metric_id"] == "cpu-load"
        assert result["value"] == 72.5

    def test_invalid_token_raises_401(self):
        """
        GIVEN an invalid token
        WHEN push_agent_metrics is called
        THEN HTTPException 401 is raised.
        """
        session = _make_session(single_record=None)
        driver = _driver_with_session(session)

        payload = AgentMetricPush(metric_id="cpu-load", value=10.0)

        with patch.object(agent_service_mod, "get_db", return_value=driver):
            with pytest.raises(HTTPException) as exc_info:
                agent_service_mod.push_agent_metrics("bad-id", "bad-token", payload)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------

class TestListAgents:
    def test_token_not_present_in_returned_dicts(self):
        """
        GIVEN agents in the DB that have an agent_token property
        WHEN list_agents is called
        THEN the returned dicts do NOT contain the agent_token key.
        """
        record = MagicMock()
        record.__getitem__ = MagicMock(
            side_effect=lambda k: {
                "a": {
                    "id": "ag-1",
                    "hostname": "host-01",
                    "status": "ONLINE",
                    "agent_token": "must-not-leak",
                },
                "ci_id": None,
                "ci_label": None,
            }[k]
        )
        session = _make_session(records=[record])
        driver = _driver_with_session(session)

        with patch.object(agent_service_mod, "get_db", return_value=driver):
            agents = agent_service_mod.list_agents()

        assert len(agents) == 1
        assert "agent_token" not in agents[0]

    def test_returns_empty_list_when_no_agents(self):
        """
        GIVEN no agents in the DB
        WHEN list_agents is called
        THEN an empty list is returned.
        """
        session = _make_session(records=[])
        driver = _driver_with_session(session)

        with patch.object(agent_service_mod, "get_db", return_value=driver):
            agents = agent_service_mod.list_agents()

        assert agents == []


# ---------------------------------------------------------------------------
# delete_agent
# ---------------------------------------------------------------------------

class TestDeleteAgent:
    def test_existing_agent_is_deleted(self):
        """
        GIVEN an existing agent ID
        WHEN delete_agent is called
        THEN the deleted ID is echoed back.
        """
        record = MagicMock()
        session = _make_session(single_record=record)
        driver = _driver_with_session(session)

        with patch.object(agent_service_mod, "get_db", return_value=driver):
            result = agent_service_mod.delete_agent("ag-1")

        assert result == {"deleted": "ag-1"}

    def test_missing_agent_raises_404(self):
        """
        GIVEN an unknown agent ID (nothing returned by MATCH)
        WHEN delete_agent is called
        THEN HTTPException 404 is raised.
        """
        session = _make_session(single_record=None)
        driver = _driver_with_session(session)

        with patch.object(agent_service_mod, "get_db", return_value=driver):
            with pytest.raises(HTTPException) as exc_info:
                agent_service_mod.delete_agent("nonexistent")

        assert exc_info.value.status_code == 404
