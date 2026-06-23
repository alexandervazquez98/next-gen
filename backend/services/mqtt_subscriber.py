# Backward-compat shim — actual implementations live in services/mqtt/
from services.mqtt.parsers.bliiot_s475e import (  # noqa: F401
    parse_telemetry_topic,
    process_telemetry_message,
)
from services.mqtt.subscriber import mqtt_subscriber_loop  # noqa: F401
