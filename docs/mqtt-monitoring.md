# MQTT monitoring integration

MQTT monitoring is now integrated as a backend/runtime pipeline: raw MQTT readings remain inspectable as non-KPI telemetry, and only explicitly approved mappings can promote MQTT samples into monitoring metrics and events.

## Current state

| Area | Status | Notes |
| --- | --- | --- |
| Raw MQTT visibility | Available | `/api/mqtt/devices`, `/api/mqtt/devices/{device_id}/metrics`, and `/api/mqtt/readings` return `RAW_MQTT_NON_KPI` data with `kpi_eligible=false`. |
| Permissions | Available | `MQTT_READ` protects read/status APIs; `MQTT_MAPPING_MANAGE` protects mapping and threshold mutations. |
| Mapping lifecycle | Available | Mappings start as `DRAFT`; only `APPROVED` mappings can bridge samples into monitoring. `REVOKED` mappings are fail-closed. |
| Thresholds | Available | Manual thresholds are stored per mapping and included in event evaluation payloads. |
| KPI/event bridge | Available | Approved numeric MQTT samples write Timescale metric values and reuse the existing event writer path. |
| Runtime subscriber | Available | A dedicated `mqtt-subscriber` Compose service runs `python -m scripts.mqtt_subscriber`. |
| Frontend UI | Not implemented | Operators currently use the backend API. |
| Auto-mapping | Not implemented | Mapping is manual by design; no automatic matching is performed. |

## Runtime topology

```text
MQTT broker
  │
  ▼
mqtt-subscriber container
  │ parses topics/payloads
  ▼
raw Device/Metric graph records                 ──► /api/mqtt/readings
  │
  ├─ no approved mapping ──► stop: RAW_MQTT_NON_KPI only
  │
  └─ approved mapping
       │
       ├─ idempotent receipt guard
       ├─ Timescale metric_values write
       └─ existing event_writer threshold path
```

The API container does **not** own the subscriber by default. The dedicated subscriber process is the normal runtime owner. The API process only starts an embedded subscriber when `ENABLE_MQTT_SUBSCRIBER=true` is explicitly set.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MQTT_BROKER_URL` | required in Compose subscriber service | Broker connection URL. Set this explicitly for deployment. |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | empty | Optional broker credentials. |
| `MQTT_CLIENT_ID` | `nexgen_subscriber` in Compose | Subscriber client identity. |
| `MQTT_MAPPING_BRIDGE_ENABLED` | `true` | Enables approved-mapping bridge writes after raw persistence. Set `false` to keep raw ingestion only. |
| `MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS` | `90` | Preferred stale-heartbeat threshold for `/api/mqtt/status`. |
| `MQTT_MAPPING_BRIDGE_MISSED_HEARTBEAT_SECONDS` | compatibility alias | Legacy alias still accepted when the preferred variable is absent. |
| `ENABLE_MQTT_SUBSCRIBER` | `false` for API process, `true` in subscriber service | Prevents accidental duplicate subscriber ownership. |

## API quick path

1. Read raw telemetry:
   - `GET /api/mqtt/devices`
   - `GET /api/mqtt/devices/{device_id}/metrics`
   - `GET /api/mqtt/readings`
2. Create a mapping as draft:
   - `POST /api/mqtt/mappings`
3. Approve the mapping:
   - `POST /api/mqtt/mappings/{mapping_id}/approve`
4. Configure thresholds:
   - `PUT /api/mqtt/mappings/{mapping_id}/thresholds`
5. Check runtime status:
   - `GET /api/mqtt/status`

## Safety rules

- Raw MQTT data is never KPI-eligible by default.
- `DRAFT`, `REVOKED`, unmapped, ambiguous, or non-numeric readings do not write Timescale samples or events.
- Duplicate MQTT payloads are deduplicated by deterministic receipt keys.
- Partial failures retry only the missing step: event retries do not rewrite the metric sample.
- Event writer calls use the existing advisory-lock path to avoid duplicate active events.
- Status-store failures are best-effort and must not stop raw ingestion.

## Deployment checklist

- [ ] Apply Neo4j migrations `003_mqtt_monitoring_mapping.cypher` and `004_mqtt_metric_result_idempotency.cypher`.
- [ ] Ensure PostgreSQL tables for runtime status and sample receipts can be created by the backend role.
- [ ] Set `MQTT_BROKER_URL` explicitly for `mqtt-subscriber`.
- [ ] Start the dedicated subscriber service: `docker compose up -d mqtt-subscriber`.
- [ ] Confirm `/api/mqtt/status` becomes fresh/non-stale after the subscriber connects.
- [ ] Confirm raw readings appear before approving any mapping.
- [ ] Approve one test mapping and verify only that mapping writes monitoring data.

## Known gaps and follow-up work

- Frontend UX for mapping review/approval is tracked in [#385](https://github.com/alexandervazquez98/next-gen/issues/385).
- Mapping/threshold audit trail and operator-facing audit views are tracked in [#386](https://github.com/alexandervazquez98/next-gen/issues/386).
- Production smoke automation for absent-vs-active subscriber status is tracked in [#387](https://github.com/alexandervazquez98/next-gen/issues/387).
