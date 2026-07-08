"""Dedicated MQTT subscriber runtime entrypoint."""

from __future__ import annotations

import asyncio
import logging

from services.mqtt.subscriber import mqtt_subscriber_loop
from services.mqtt_runtime_status import get_mqtt_runtime_status_service

logger = logging.getLogger(__name__)


def _safe_status_update(action: str, callback):
    """Best-effort runtime status update that never owns process liveness."""
    try:
        callback()
    except Exception:
        logger.warning("[MQTT] Runtime status update failed during %s", action, exc_info=True)


async def run_mqtt_subscriber() -> None:
    """Run the shared MQTT subscriber process until cancellation or failure."""
    status_service = get_mqtt_runtime_status_service()
    _safe_status_update("mark_configured", lambda: status_service.mark_configured(True))

    try:
        await mqtt_subscriber_loop()
    finally:
        # Any shutdown path is reflected in shared status for API-process observability.
        _safe_status_update("shutdown", lambda: status_service.record_disconnect("SHUTDOWN"))


def main(argv=None) -> int:
    """CLI-compatible entrypoint for ``python -m scripts.mqtt_subscriber``."""
    del argv

    try:
        asyncio.run(run_mqtt_subscriber())
        return 0
    except KeyboardInterrupt:
        _safe_status_update(
            "shutdown",
            lambda: get_mqtt_runtime_status_service().record_disconnect("SHUTDOWN"),
        )
        return 0
    except Exception as exc:
        error_text = str(exc)
        _safe_status_update(
            "runtime_error",
            lambda error_text=error_text: get_mqtt_runtime_status_service().record_disconnect(
                "RUNTIME_ERROR",
                error_text,
            ),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
