# Exploration: Integrate MQTT readings into monitoring metrics

## Issue

GitHub issue #321: `feat(mqtt): integrate MQTT readings into monitoring metrics`.

## Executive summary

The current MQTT implementation is split from the existing monitoring product model. MQTT telemetry is parsed and persisted as generic `Device` + `Metric` data, but operational monitoring screens and alerting remain centered on `CI` + `MetricDef`, Timescale `metric_values`, and event generation from CI metric cycles.

This means MQTT support is an ingestion foundation, not yet an operational monitoring feature. The integration must add an explicit mapping boundary so raw MQTT readings can stay observable without silently becoming official monitoring KPIs.

## Current-state findings

### MQTT ingestion exists but is isolated

MQTT telemetry parses through backend MQTT subscriber/service code and persists into the generic device model, roughly:

```text
(:Device)-[:HAS_METRIC]->(:Metric)
```

Relevant evidence reported during exploration:

- `backend/services/mqtt/subscriber.py`
- `backend/migrations/002_generic_device_schema.cypher`
- `DeviceMetricRepo`

### Monitoring remains CI/MetricDef-centric

Existing monitoring and alerting paths use the operational CI metric model:

```text
(:CI)-[:HAS_METRIC]->(:MetricDef)
```

Samples are written to the historical metric store and events are generated from CI metric cycles.

Relevant evidence reported during exploration:

- `backend/services/snmp_service.py`
- `backend/polling/event_writer.py`
- Timescale `metric_values`
- `CI` / `MetricDef` model paths

### Runtime subscriber wiring is incomplete

The MQTT subscriber loop is not currently production-started as part of the main app or compose runtime.

Relevant evidence reported during exploration:

- `mqtt_subscriber_loop()` is not started from `backend/main.py`.
- `docker-compose.yml` does not define a dedicated MQTT subscriber service/entrypoint.

### Frontend monitoring has no MQTT visibility path

Frontend monitoring reads CI/event/node-oriented resources and does not expose raw MQTT `Device` / `Metric` streams or mapping state.

Relevant evidence reported during exploration:

- `frontend/hooks/queries/useMonitoringConsoleData.ts`
- `frontend/services/queryResources.ts`
- `frontend/components/MonitoringConsole.tsx`

### Product boundary already exists in docs/contracts

The current polling contracts reportedly reject production MQTT with a boundary similar to:

```text
Production MQTT is out of scope; use MQTT_STUB for roadmap sizing.
```

So #321 should intentionally change the roadmap boundary rather than accidentally bypass it.

## Key product boundary

MQTT readings must not silently pollute official monitoring KPIs.

Required boundary:

1. Raw MQTT ingestion remains available as `Device` + `Metric` observability.
2. Operators must explicitly map MQTT devices/readings to monitoring entities.
3. Only mapped readings may enter CI/MetricDef monitoring views, Timescale history, thresholds, or event generation.
4. Unmapped readings must remain visible but excluded from official monitoring KPIs.
5. MQTT remains stream ingestion, not SNMP-style polling.

## Risks

- **Domain bridge risk**: no explicit bridge exists from `Device`/`Metric` to `CI`/`MetricDef`.
- **Runtime risk**: MQTT subscriber is not wired into app startup or compose runtime.
- **Data pollution risk**: auto-mapping arbitrary MQTT payloads could corrupt monitoring semantics and KPIs.
- **Frontend visibility risk**: operators currently have no clear place to see unmapped MQTT data or mapping status.
- **Threshold/event risk**: MQTT-derived metric event semantics are not yet specified.
- **Migration/operations risk**: generic device schema is additive, but runtime migration/apply sequence needs verification.

## Proposal inputs

The proposal should define a sliced integration plan:

1. Runtime: make MQTT subscriber an explicit operational service/process.
2. Raw observability: expose raw MQTT devices/metrics and unmapped state.
3. Mapping: add operator-controlled mapping from MQTT `Device`/`Metric` to `CI`/`MetricDef`.
4. Persistence: write selected mapped readings into the existing historical metric store.
5. Events: define threshold/event semantics for mapped MQTT readings.
6. Frontend/admin: provide visibility for unmapped readings and mapping actions.
7. Runbook: document end-to-end verification and safe deployment.

## Artifact status

This OpenSpec exploration artifact was reconstructed by the parent orchestrator from the delegated exploration findings after the delegated phase twice failed to create a readable OpenSpec file in the worktree. The findings were also persisted by the subagent to Engram topic `sdd/integrate-mqtt-readings-monitoring/explore`.
