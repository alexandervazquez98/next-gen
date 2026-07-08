# Proposal: Integrate MQTT Readings into Monitoring Metrics (MVP: backend/API first)

## Intent
Integrate MQTT telemetry into the operational monitoring pipeline while preventing silent KPI contamination by requiring explicit operator-approved mapping from raw MQTT devices/metrics into existing CI/MetricDef monitoring semantics.

## Scope
### In-scope (MVP slice)
1. Treat MQTT raw `Device`/`Metric` as first-class, observable data that remains visible through backend/API surfaces even when unmapped.
2. Add explicit, auditable mapping configuration owned by operators that links MQTT `Device`/`Metric` entries to existing CI/MetricDef monitoring entities.
3. Gate Timescale KPI persistence and event generation so only mapped readings can enter official monitoring KPIs.
4. Expose manual threshold configuration for mapped MQTT metrics (create/read/update thresholds used by existing event rules path).
5. Ensure MQTT ingestion + mapping integration is explicitly wired for runtime execution so this path is operational, not implicit.

### Out-of-scope (for first slice)
1. UI-driven mapping workflows and unmapped-readings dashboards in the monitoring console.
2. Auto-mapping behavior that infers mappings without operator action.
3. KPI/alert model changes beyond what is needed to route mapped MQTT readings into existing paths.
4. Backfilling historical MQTT data into Timescale as legacy KPI history.

## Affected areas
- **Backend MQTT ingestion/runtime**: startup wiring, observability, and API-facing status for raw readings.
- **Monitoring model bridge**: new mapping layer from generic MQTT `Device`/`Metric` into `CI`/`MetricDef`.
- **Timescale/event ingestion contract**: only accept mapped MQTT payloads for metric persistence and event derivation.
- **Monitoring API**: endpoints for mapping configuration and threshold management (API-first delivery).
- **Audit/logging**: mapping decisions and source attribution to guarantee no silent semantic drift.

## Risks
- **Semantic contamination risk**: unmapped MQTT data accidentally reaching KPI pipelines. Mitigation: hard enforcement at bridge boundary and explicit mapping checks in all write/event paths.
- **Governance risk**: inconsistent mapping decisions across teams/projects. Mitigation: role-based mapping updates, audit trail, and explicit approval semantics.
- **Operational drift risk**: raw and mapped views diverge. Mitigation: deterministic mapping resolution and drift telemetry.
- **Runtime risk**: MQTT subscriber/process not started in all deployment modes. Mitigation: explicit run mode checks and startup validation.
- **Support risk**: teams confuse raw visibility with official monitoring signals. Mitigation: clear API labeling and contract docs in change.

## Rollback plan
1. Disable mapping rule(s) via API/config to stop new mapped KPI writes instantly.
2. Reconfigure runtime to run MQTT ingestion in raw-observability mode only (no mapping bridge writes).
3. If needed, remove mapping rules from persistence/flags and keep raw Device/Metric records intact for recovery and troubleshooting.
4. Leave Timescale/event tables untouched for unmapped records since only mapped data should have been inserted.

## Success criteria
- Raw MQTT readings are ingested and available through backend/API without being treated as official monitoring KPIs by default.
- Only readings with an approved operator mapping are persisted as monitoring KPI samples.
- Threshold config for mapped MQTT metrics is stored and applied through existing event flow.
- Unmapped readings remain queryable/visible via backend/API and are clearly excluded from official KPI/alert datasets.
- There is auditable evidence of mapping actions and source-to-KPI transformation for each metric lineage.

## Proposal question round
### Assumptions currently in scope (from provided decisions)
- First value slice is backend/API-first, with no UI requirements.
- Mapping is manual and operator-approved only.
- Unmapped readings are exposed by API/backend, but excluded from KPI math.
- Threshold settings for mapped metrics are configurable manually.

### Questions for owner review
1. **Operator control**: Which roles/teams are allowed to create and approve mapping rules, and should approval require a second confirmation step?
2. **Threshold ownership**: Should threshold configs be global per MetricDef, per mapping, or tenant/context-scoped?
3. **Visibility model**: Should unmapped raw MQTT endpoints be internal-only (admin/ops) in MVP, or exposed to platform customers as read-only technical telemetry?
4. **Error handling**: For mapped readings that fail processing, should we reject all samples for that mapping immediately or only skip bad samples and alert continuously?
5. **Run boundary**: Should mapping changes be immediate-on-write, or staged via versioned rule activation window for safer operations?

### Next-step assumption summary
Unless corrected, the proposal assumes the above constraints are fixed for MVP and that any UI work is intentionally deferred to later slices.
