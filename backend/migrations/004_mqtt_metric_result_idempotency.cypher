// PR4 MQTT bridge idempotency guard for replay-safe event/result writes.

CREATE CONSTRAINT metric_result_idempotency_key_unique IF NOT EXISTS
FOR (r:MetricResult) REQUIRE r.idempotency_key IS UNIQUE;
