# Proposal: MQTT Monitoring Frontend UX (Browse Raw + Manage Mappings)

## Intent

`backend/routers/mqtt.py` already exposes the endpoints, but operators still drive raw readings + mapping lifecycle via curl. Issue #385 wants the operator UI: browse raw MQTT, manage mapping drafts, approve/revoke mappings, edit thresholds — under the safety model (non-KPI raw, no auto-mapping, permission-gated mutations).

## Scope

### In Scope

- New route `/monitoring/mqtt` + gated sidebar entry (`MQTT_READ` / admin).
- Browse raw devices, per-device metrics, latest readings; always surface `RAW_MQTT_NON_KPI` + `kpi_eligible=false`.
- Create/edit draft mappings (DRAFT only); approve/revoke behind confirm modal; edit thresholds on APPROVED only.
- Bridge status + counters from `/mqtt/status` on a fixed interval.

### Out of Scope

- Backend API changes — every endpoint exists. No auto-mapping, KPI math, alert rules, backfill, or bulk import.

## Capabilities

### New Capabilities

- `mqtt-monitoring-frontend`: raw browse + runtime status + non-KPI visualization.
- `mqtt-mapping-management`: draft CRUD, approve/revoke, threshold edits with confirm + permission gates.

### Modified Capabilities

- None. Backend `mqtt-monitoring-integration` lives in `openspec/changes/integrate-mqtt-readings-monitoring/`; this change does not alter its requirements.

## Approach

Mirror existing patterns: query-key factories (`mqttDevices/metrics/readings/status/mappings/mappingThresholds`), seven fetchers, hooks that invalidate `mqtt*` keys after each mutation. One `MqttMonitoringPage.tsx` with four tabs (Raw Readings, Mappings, Thresholds, Bridge Status). Wire `<NavItem>` + `<Route>` in `App.tsx` gated by `hasPermission("MQTT_READ")`. Mutations gated by `MQTT_MAPPING_MANAGE`; `403` → toast. Approve/revoke via confirm modal naming id + target CI; threshold edits disabled unless APPROVED.

## Affected Areas

- Modified: `App.tsx`, `queryKeys.ts`, `queryResources.ts`, `types.ts`.
- New: `MqttMonitoringPage.tsx`, `MqttConfirmModal.tsx`, query/mutation hooks, type exports, tests.

## Risks

- **Raw looks like KPI**: persistent `RAW_MQTT_NON_KPI` badge, no "mark as KPI" affordance.
- **Wrong mapping approved/revoked**: confirm modal names id + target CI + source metric; second-click.
- **Stale cache**: invalidate `mqtt*` keys + `systemStatus` (if KPI-derived) after each mutation.
- **Partial-edit overwrite**: full-payload mutations; re-fetch before edit form.
- **CI/MetricDef picker gap**: reuse `/nodes` + `/metrics`; record gap.
- **Threshold on non-APPROVED**: control disabled with tooltip; `409` → inline error.

## Rollback Plan

Revert the frontend change in the branch: drop `<NavItem>`/`<Route>` in `App.tsx`, restore prior fetcher/hook/type exports. No DB migration or Timescale rollback. Optionally gate behind `VITE_MQTT_UI`.

## Dependencies

- `/api/mqtt/*` endpoints (verified in `backend/routers/mqtt.py`).
- `MQTT_READ` + `MQTT_MAPPING_MANAGE` permissions in UserPermission enum + seed roles.
- React Query v5 + `hasPermission` from `context/AuthContext.tsx`.

## Success Criteria

- [ ] `MQTT_READ` operator browses devices/metrics/readings; `kpi_eligible=false` always visible.
- [ ] `MQTT_MAPPING_MANAGE` operator does full CRUD; controls hidden otherwise; `403` → toast.
- [ ] Thresholds editable only on APPROVED mappings; control disabled with tooltip; `409` inline.
- [ ] Approve/revoke require confirm naming id + target CI.
- [ ] Vitest + RTL covers permission gating, confirm flow, threshold-disabled state.
