import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import get_db
from fastapi import HTTPException
from models.core import AgentRegistration, AgentMetricPush

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_agent(payload: AgentRegistration) -> Dict[str, Any]:
    """
    Register a new remote Antigravity agent or re-register an existing one
    (matched by hostname).  Returns the agent node plus a token that the
    agent must present for subsequent calls.
    """
    driver = get_db()
    with driver.session() as session:
        # Check if an agent with the same hostname already exists
        existing = session.run(
            "MATCH (a:Agent {hostname: $hostname}) RETURN a LIMIT 1",
            hostname=payload.hostname,
        ).single()

        if existing:
            agent_node = dict(existing["a"])
            agent_id = agent_node["id"]
            agent_token = agent_node["agent_token"]
            # Update mutable fields and mark as ONLINE
            session.run(
                """
                MATCH (a:Agent {id: $id})
                SET a.ip = $ip,
                    a.os = $os,
                    a.version = $version,
                    a.status = 'ONLINE',
                    a.last_seen = $now
                """,
                id=agent_id,
                ip=payload.ip,
                os=payload.os,
                version=payload.version,
                now=_now_iso(),
            )
        else:
            agent_id = str(uuid.uuid4())
            agent_token = str(uuid.uuid4())
            now = _now_iso()
            session.run(
                """
                CREATE (a:Agent {
                    id: $id,
                    hostname: $hostname,
                    ip: $ip,
                    os: $os,
                    version: $version,
                    status: 'ONLINE',
                    registered_at: $now,
                    last_seen: $now,
                    agent_token: $token
                })
                """,
                id=agent_id,
                hostname=payload.hostname,
                ip=payload.ip,
                os=payload.os,
                version=payload.version,
                now=now,
                token=agent_token,
            )

        # Optionally link agent to CI
        if payload.ci_id:
            session.run(
                """
                MATCH (a:Agent {id: $agent_id}), (ci:CI {id: $ci_id})
                MERGE (a)-[:MONITORS]->(ci)
                """,
                agent_id=agent_id,
                ci_id=payload.ci_id,
            )

        return {"id": agent_id, "agent_token": agent_token, "status": "ONLINE"}


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def agent_heartbeat(agent_id: str, agent_token: str) -> Dict[str, Any]:
    """Update an agent's last_seen timestamp and mark it ONLINE."""
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            "MATCH (a:Agent {id: $id, agent_token: $token}) RETURN a LIMIT 1",
            id=agent_id,
            token=agent_token,
        ).single()

        if not result:
            raise HTTPException(status_code=401, detail="Invalid agent credentials")

        session.run(
            """
            MATCH (a:Agent {id: $id})
            SET a.status = 'ONLINE', a.last_seen = $now
            """,
            id=agent_id,
            now=_now_iso(),
        )
        return {"status": "ONLINE", "last_seen": _now_iso()}


# ---------------------------------------------------------------------------
# Metric Push
# ---------------------------------------------------------------------------


def push_agent_metrics(
    agent_id: str, agent_token: str, payload: AgentMetricPush
) -> Dict[str, Any]:
    """
    Accept a single metric value pushed by a remote agent and update the
    MetricDef node's live value in Neo4j.
    """
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            "MATCH (a:Agent {id: $id, agent_token: $token}) RETURN a LIMIT 1",
            id=agent_id,
            token=agent_token,
        ).single()

        if not result:
            raise HTTPException(status_code=401, detail="Invalid agent credentials")

        # Update last_seen
        session.run(
            "MATCH (a:Agent {id: $id}) SET a.last_seen = $now",
            id=agent_id,
            now=_now_iso(),
        )

        # Update the MetricDef live value (creates a `last_value` property)
        session.run(
            """
            MATCH (m:MetricDef {id: $metric_id})
            SET m.last_value = $value,
                m.last_unit = $unit,
                m.last_updated = $now
            """,
            metric_id=payload.metric_id,
            value=payload.value,
            unit=payload.unit,
            now=_now_iso(),
        )

        return {"accepted": True, "metric_id": payload.metric_id, "value": payload.value}


# ---------------------------------------------------------------------------
# List / Delete (admin operations)
# ---------------------------------------------------------------------------


def list_agents() -> List[Dict[str, Any]]:
    """Return all registered agents (token is omitted for security)."""
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (a:Agent)
            OPTIONAL MATCH (a)-[:MONITORS]->(ci:CI)
            RETURN a, ci.id AS ci_id, ci.label AS ci_label
            ORDER BY a.registered_at DESC
            """
        )
        agents = []
        for record in result:
            agent = dict(record["a"])
            agent.pop("agent_token", None)  # Never expose token in listings
            agent["ci_id"] = record["ci_id"]
            agent["ci_label"] = record["ci_label"]
            agents.append(agent)
        return agents


def delete_agent(agent_id: str) -> Dict[str, str]:
    """Deregister and remove an agent node."""
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            "MATCH (a:Agent {id: $id}) RETURN a LIMIT 1", id=agent_id
        ).single()

        if not result:
            raise HTTPException(status_code=404, detail="Agent not found")

        session.run(
            "MATCH (a:Agent {id: $id}) DETACH DELETE a", id=agent_id
        )
        return {"deleted": agent_id}
