# Tasks: MQTT Monitoring Frontend UX

## Review Workload Forecast

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

1000–1300 lines. If apply >800: PR1 = WU1+WU2+WU3; PR2 = WU4+WU5+WU6.

### Suggested Work Units

| Unit | Goal | Test command | Runtime | Rollback |
|------|------|--------------|---------|----------|
| 1 | Foundation + page shell | `pnpm test services` | manual nav | revert 6 new files + App.tsx route |
| 2 | Raw + badge + bridge | `pnpm test components/mqtt` | manual tabs | drop 3 mqtt components |
| 3 | Mappings + forms + confirm | `pnpm test MappingsTab` | manual DRAFT/Approve/Threshold | drop 4 mqtt components |
| 4 | Vitest page integration | `pnpm test MqttMonitoringPage` | N/A (RTL) | remove page test file |
| 5 | Playwright E2E | `pnpm test:e2e mqtt-monitoring` | N/A (Playwright) | remove e2e spec file |
| 6 | Verification gate | `pnpm test` + `test:e2e mqtt-monitoring` | N/A | n/a |

## Phase 1: Foundation

- [ ] 1.1 Append MQTT interfaces to `frontend/types.ts`.
- [ ] 1.2 Append MQTT key factories to `frontend/services/queryKeys.ts`.
- [ ] 1.3 Append fetchers + mutators to `frontend/services/queryResources.ts`.
- [ ] 1.4 Create `frontend/hooks/queries/useMqttQueries.ts` — 6 read hooks; readings + status `refetchInterval:5000`.
- [ ] 1.5 Create `frontend/hooks/queries/useMqttMutations.ts` — 5 mutations; 403 toast; invalidate `mqtt*` + `systemStatus` on approve/revoke.

## Phase 2: Nav + Route + Page

- [ ] 2.1 Add gated `<NavItem to="/monitoring/mqtt">` + `<Route path="monitoring/mqtt">` in `frontend/App.tsx`.
- [ ] 2.2 Create `frontend/components/MqttMonitoringPage.tsx` — tab host; `hasPermission` → `<Navigate to="/">`; no fetch on deny.

## Phase 3: Raw + Bridge

- [ ] 3.1 Create `frontend/components/mqtt/RawNonKpiBadge.tsx` — defaults `RAW_MQTT_NON_KPI`; renders `kpi_eligible=false`; amber column.
- [ ] 3.2 Create `frontend/components/mqtt/MqttRawReadingsTab.tsx` — devices + expand-metrics + Latest Readings; every row mounts badge.
- [ ] 3.3 Create `frontend/components/mqtt/MqttBridgeStatusTab.tsx` — 3 branches (Running/Not Running/Not Configured) + reason_code/last_error/last_message_at.

## Phase 4: Mappings + Forms + Confirm

- [ ] 4.1 Create `frontend/components/mqtt/MqttMappingsTab.tsx` — filter + table; write controls gated by `MQTT_MAPPING_MANAGE`; 403 toast.
- [ ] 4.2 Create `frontend/components/mqtt/MqttMappingForm.tsx` — DRAFT-only CRUD; re-fetch before edit; full-payload PUT; inline errors.
- [ ] 4.3 Create `frontend/components/mqtt/MqttThresholdForm.tsx` — 3 inputs disabled w/ tooltip unless APPROVED; `409` inline.
- [ ] 4.4 Create `frontend/components/mqtt/MqttConfirmModal.tsx` — lists `mapping_id`+`target_ci_id`+`source_metric_name`; Cancel no-call; Confirm fires.

## Phase 5: Vitest RED Tests

- [ ] 5.1 RED `RawNonKpiBadge.test.tsx` — defaults on missing; renders `classification`+`kpi_eligible=false`.
- [ ] 5.2 RED `MqttConfirmModal.test.tsx` — Cancel = no `api.post`; Confirm fires on click; lists 3 identity fields.
- [ ] 5.3 RED `MqttMappingForm.test.tsx` — DRAFT prefill; full-payload PUT; missing fields skip submit.
- [ ] 5.4 RED `MqttThresholdForm.test.tsx` — disabled when status≠APPROVED; tooltip; `409` inline.
- [ ] 5.5 RED `MqttMonitoringPage.test.tsx` — 3 permission gates, badge default, no-promotion regex, confirm-cancel, `409` inline.

## Phase 6: E2E + Verification

- [ ] 6.1 Create `frontend/test/e2e/mqtt-monitoring.spec.ts` — login → `/monitoring/mqtt` → Approve confirm → APPROVED row → `systemStatus` refetched via `waitFor`.
- [ ] 6.2 Run `pnpm test` + `pnpm test:e2e mqtt-monitoring`; manual walk raw → draft → Approve → APPROVED threshold.