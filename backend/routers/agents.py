from fastapi import APIRouter, Depends, Header
from typing import Any, Dict, List, Optional

from models.core import AgentRegistration, AgentMetricPush
from models.user import User
from services.auth_service import get_current_active_user
import services.agent_service as agent_service

router = APIRouter(
    prefix="/api/agents",
    tags=["Agents"],
    responses={404: {"description": "Not found"}},
)


@router.post("/register", response_model=Dict[str, Any])
async def register_agent(payload: AgentRegistration):
    """
    Register a new remote Antigravity agent (or re-register an existing one).
    Returns the ``agent_token`` that the agent must use for subsequent calls.
    This endpoint is intentionally unauthenticated so that agents can
    self-register on first boot without needing a pre-provisioned JWT.
    """
    return agent_service.register_agent(payload)


@router.post("/{agent_id}/heartbeat", response_model=Dict[str, Any])
async def agent_heartbeat(
    agent_id: str,
    x_agent_token: str = Header(..., alias="X-Agent-Token"),
):
    """
    Agents call this endpoint periodically to signal they are still ONLINE.
    Requires the ``X-Agent-Token`` header returned at registration time.
    """
    return agent_service.agent_heartbeat(agent_id, x_agent_token)


@router.post("/{agent_id}/metrics", response_model=Dict[str, Any])
async def push_metrics(
    agent_id: str,
    payload: AgentMetricPush,
    x_agent_token: str = Header(..., alias="X-Agent-Token"),
):
    """
    Accept a telemetry metric value pushed by a remote agent.
    Requires the ``X-Agent-Token`` header returned at registration time.
    """
    return agent_service.push_agent_metrics(agent_id, x_agent_token, payload)


@router.get("", response_model=List[Dict[str, Any]])
async def list_agents(current_user: User = Depends(get_current_active_user)):
    """
    List all registered remote agents.  Requires authentication.
    The ``agent_token`` field is never included in this response.
    """
    return agent_service.list_agents()


@router.delete("/{agent_id}", response_model=Dict[str, str])
async def delete_agent(
    agent_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """
    Deregister and permanently remove an agent.  Requires authentication.
    """
    return agent_service.delete_agent(agent_id)
