"""Escalation Notifier — sends critical AI event escalations to human reviewers.

Publishes to MQTT topic `alerts/human/escalation` when an AI agent attempts
to close a CRITICAL event, requiring human approval before proceeding.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import get_mqtt_settings

logger = logging.getLogger(__name__)

# Singleton: track active escalations in-memory (keyed by escalation_id)
_active_escalations: dict[str, dict] = {}
_lock = threading.Lock()

# Escalation timeout in minutes
ESCALATION_TIMEOUT_MINUTES = 30


def _build_escalation_payload(
    ai_persona: str,
    ai_agent_id: str,
    event_id: str,
    event_message: str,
    ci_id: str,
    ci_name: str,
    escalation_id: str,
    timeout_at: str,
) -> dict:
    """Build the escalation payload for MQTT publishing."""
    return {
        "escalation_id": escalation_id,
        "ai_persona": ai_persona,
        "ai_agent_id": ai_agent_id,
        "event_id": event_id,
        "event_message": event_message,
        "ci_id": ci_id,
        "ci_name": ci_name,
        "timeout_at": timeout_at,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "topic": "alerts/human/escalation",
    }


async def notify_critical_event_escalation(
    ai_persona: str,
    ai_agent_id: str,
    event_id: str,
    event_message: str,
    ci_id: str,
    ci_name: str,
) -> dict:
    """Notify human reviewer that AI wants to close a CRITICAL event.

    Publishes to MQTT topic `alerts/human/escalation` with the event details.
    Returns escalation ticket info with 30-minute timeout.

    Args:
        ai_persona: AI persona (e.g., "AI_OPERATOR")
        ai_agent_id: JWT subject identifying the agent
        event_id: ID of the event being closed
        event_message: Event message/description
        ci_id: CI that triggered the event
        ci_name: Human-readable CI name

    Returns:
        Escalation info dict with keys:
        - escalation_id: unique ID for this escalation
        - timeout_at: ISO timestamp when escalation expires
        - topic: MQTT topic the escalation was published to
    """
    escalation_id = str(uuid.uuid4())
    timeout_at = (
        datetime.now(timezone.utc) + timedelta(minutes=ESCALATION_TIMEOUT_MINUTES)
    ).isoformat()

    payload = _build_escalation_payload(
        ai_persona=ai_persona,
        ai_agent_id=ai_agent_id,
        event_id=event_id,
        event_message=event_message,
        ci_id=ci_id,
        ci_name=ci_name,
        escalation_id=escalation_id,
        timeout_at=timeout_at,
    )

    # Store locally for tracking
    with _lock:
        _active_escalations[escalation_id] = payload.copy()

    # Publish to MQTT
    try:
        import aiomqtt

        mqtt_settings = get_mqtt_settings()
        # Parse broker URL (same logic as mqtt_subscriber.py)
        broker_url = mqtt_settings.broker_url
        if broker_url.startswith("mqtt://"):
            host_port = broker_url[7:]
            if ":" in host_port:
                host, port_str = host_port.rsplit(":", 1)
                port = int(port_str)
            else:
                host = host_port
                port = 1883
        else:
            host = broker_url
            port = 1883

        async with aiomqtt.connect(
            host=host,
            port=port,
            username=mqtt_settings.username,
            password=mqtt_settings.password,
            client_id=f"escalation-notifier-{ai_agent_id[:8]}",
            timeout=5.0,
        ) as client:
            await client.publish(
                "alerts/human/escalation",
                payload=json.dumps(payload),
                qos=1,
            )
        logger.info(
            "[ESCALATION] Published critical event escalation %s for event %s",
            escalation_id,
            event_id,
        )
    except ImportError:
        logger.warning(
            "[ESCALATION] aiomqtt not installed — escalation %s not published to MQTT "
            "(event_id=%s, ci_id=%s)",
            escalation_id,
            event_id,
            ci_id,
        )
        return {
            "escalation_id": escalation_id,
            "timeout_at": timeout_at,
            "topic": "alerts/human/escalation",
            "success": False,
        }
    except Exception as e:
        logger.error(
            "[ESCALATION] Failed to publish escalation %s: %s",
            escalation_id,
            e,
        )
        with _lock:
            _active_escalations.pop(escalation_id, None)
        return {
            "escalation_id": escalation_id,
            "timeout_at": timeout_at,
            "topic": "alerts/human/escalation",
            "success": False,
        }

    return {
        "escalation_id": escalation_id,
        "timeout_at": timeout_at,
        "topic": "alerts/human/escalation",
        "success": True,
    }


def get_escalation(escalation_id: str) -> Optional[dict]:
    """Retrieve an active escalation by ID.

    Removes expired escalations on access (TTL cleanup).
    """
    with _lock:
        escalation = _active_escalations.get(escalation_id)
        if escalation is None:
            return None
        # Auto-delete if expired
        timeout_at_str = escalation.get("timeout_at")
        if timeout_at_str:
            timeout_at = datetime.fromisoformat(timeout_at_str)
            if datetime.now(timezone.utc) > timeout_at:
                _active_escalations.pop(escalation_id, None)
                return None
        return escalation


def clear_escalation(escalation_id: str) -> bool:
    """Remove an escalation from the active cache (after approval/timeout)."""
    with _lock:
        if escalation_id in _active_escalations:
            del _active_escalations[escalation_id]
            return True
        return False