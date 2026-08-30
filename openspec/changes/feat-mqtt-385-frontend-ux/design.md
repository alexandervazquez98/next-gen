# Design: MQTT Monitoring Frontend UX (Browse Raw + Manage Mappings)

## Context

`backend/routers/mqtt.py` already exposes the full lifecycle — `/mqtt/devices`, `/mqtt/readings`, `/mqtt/status`, `/mqtt/mappings` (list/create/update/approve/revoke), and `/mqtt/mappings/{id}/thresholds` — but operators drive everything via curl. Issue #385 wants a real operator UI: browse raw MQTT, manage mapping drafts, approve/revoke mappings, edit thresholds — under the same safety model the backend enforces (`MQTT_READ` for reads, `MQTT_MAPPING_MANAGE` for writes, raw readings carry `classification="RAW_MQTT_NON_KPI"` and `kpi_eligible=false`, no auto-mapping, no promotion path).

This change is **frontend-only**. Every endpoint already exists and was verified against `backend/routers/mqtt.py` and `backend/models/mqtt.py`. The integration spec lives at `openspec/changes/integrate-mqtt-readings-monitoring/specs/mqtt-monitoring-integration/spec.md` and is NOT modified here.

## Goals / Non-Goals

**Goals** (from proposal §Scope and §Success Criteria):
- One new route `/monitoring/mqtt`, gated by `MQTT_READ` (or `ADMIN`).
- Raw browse, bridge status, draft CRUD, approve/revoke, threshold edits — all under the same permission model the backend enforces.
- `RAW_MQTT_NON_KPI` badge and `kpi_eligible=false` indicator visible on every reading row; **no** "mark as KPI" affordance anywhere.
- Approve/revoke through a confirm modal that names `mapping_id`, `target_ci_id`, and `source_metric_name`; cancellation issues zero network calls.
- Threshold form editable only on APPROVED; `409` from backend surfaces inline next to the affected field.
- React Query cache invalidation wired so approve/revoke refresh the Mappings, Thresholds, raw-read, Bridge Status, AND `systemStatus` keys.

**Non-Goals**:
- Backend API changes, KPI math, alert rules, backfill, bulk import, auto-mapping, persistence/UI for the SNAPSHOT model in `docs/itsm/event-flow.md` (event-context snapshots, not live dashboards).
- Reusable Modal component library. One new confirm modal component scoped to this feature.

## Architecture

### Component tree

```
<App>
  <MainLayout>
    <NavItem to="/monitoring/mqtt" />          ← gated by hasPermission("MQTT_READ")
    <Route path="monitoring/mqtt" element={<MqttMonitoringPage />} />

<MqttMonitoringPage>
  ├─ (no MQTT_READ)            → null + redirects via Navigate("/"); never fetches
  ├─ <MqttRawReadingsTab/>     ← always visible to MQTT_READ
  │    ├─ <DeviceList/>        ← expands row → <DeviceMetrics/>
  │    ├─ <LatestReadingsPanel refetchInterval={5000}/>   (visible only when at least 1 device expanded)
  │    └─ <RawNonKpiBadge/>    ← required rendering per reading row
  ├─ <MqttMappingsTab/>        ← visible iff MQTT_READ; write controls iff MQTT_MAPPING_MANAGE
  │    ├─ <MappingsFilter/>    ← ?status=DRAFT|APPROVED|REVOKED|UNMAPPED
  │    ├─ <MappingRow/> ×N
  │    ├─ <MappingForm/>       ← create/edit (DRAFT only); prefill via re-fetch before edit
  │    ├─ <ThresholdForm/>     ← APPROVED only; otherwise inputs disabled w/ tooltip
  │    └─ <MqttConfirmModal/>  ← approve/revoke confirm; MUST include mapping_id+target_ci+source_metric
  ├─ <MqttThresholdsTab/>      ← alias of MappingsTab's threshold pane (deep-link anchor)
  └─ <MqttBridgeStatusTab/>    ← Bridge Status; <BridgeStatusCard/> polling /mqtt/status every 5s
```

### Hooks & data flow

```
UI components  ──▶  useMqtt*Query (React Query)  ──▶  fetchMqtt* (api wrapper)  ──▶  /api/mqtt/*
        ▲                              │
        │                              ▼
        └──────────  useMqtt*Mutation ──────── invalidate: mqttDevices, mqttDeviceMetrics,
                                                mqttReadings, mqttStatus, mqttMappings,
                                                mqttMappingThresholds, systemStatus*
```

`*` — `systemStatus` is invalidated only on approve/revoke (per spec §Cache Invalidation on Mutations).

## Architecture Decisions

| # | Decision | Options considered | Chosen + rationale |
|---|----------|--------------------|--------------------|
| 1 | Where the gate lives | (a) `<Route>`-level guard via `ProtectedRoute` clone, (b) component-level `if (!hasPermission) return null` | **(b)** — matches existing ITSM nav (`App.tsx` lines 139–158). Adding a third route-protector variant would duplicate logic and the spec explicitly asks for "redirect to landing page" on denied entry, which the page itself implements with `<Navigate/>`. |
| 2 | Confirm UX | (a) `window.confirm()` like `RoleManager`/`MetricsManager`, (b) in-app modal | **(b) `MqttConfirmModal`** — `window.confirm` cannot render the required mapping identity fields; spec scenario "approve opens confirm naming the mapping" requires inline display of `mapping_id`, `target_ci_id`, `source_metric_name`. |
| 3 | PUT semantics for edits | (a) PATCH-style partial, (b) full-payload PUT | **(b)** — backend `MqttMappingUpdateRequest` accepts partials, but spec scenario "submit MUST send a full-payload PUT" requires full-payload. Re-fetch latest GET before opening the form to avoid partial-edit overwrite. |
| 4 | Cache invalidation strategy | (a) optimistic update, (b) refetch on success | **(b)** — spec §Cache Invalidation on Mutations mandates post-success `invalidateQueries`. No optimistic update to keep audit trace intact and avoid rollback complexity for low-frequency operator actions. |
| 5 | Tab visibility under `MQTT_READ` only | (a) Hide write controls via CSS, (b) Hide entirely | **(b)** — buttons that "exist but do nothing" leak affordance. Spec §Permission Model "Read-only hides all write controls" → do not render. |
| 6 | Bridge status polling | (a) `refetchInterval` on `useQuery`, (b) `setInterval` + manual state | **(a)** — matches `useSystemStatusQuery` pattern (`refetchInterval: 3000`). Use 5000ms for Bridge Status since status is minutes-scale, not seconds. |
| 7 | CI / MetricDef picker for create | (a) custom autocomplete, (b) reuse `/nodes` + `/metrics` lists via existing hooks | **(b)** — proposal §Risks explicitly calls this a "CI/MetricDef picker gap" and instructs "reuse `/nodes` + `/metrics`; record gap". We do not invent a new picker; we filter existing lists. |

## Data Flow — approve flow (most safety-critical)

```
Operator clicks "Approve" on a DRAFT mapping row
        │
        ▼
<MappingsTab>  → setState({ confirmModal: { kind:'approve', mapping } })
        │
        ▼
<MqttConfirmModal>  renders: id, target_ci_id, source_metric_name
        │
        ├── operator clicks "Cancel"  → setState(null); NO fetch
        └── operator clicks "Confirm" → useApproveMappingMutation.mutate(mappingId)
                                                  │
                                                  ▼
                                       api.post(`/mqtt/mappings/${id}/approve`, {})
                                                  │
                                       ┌──────────┴──────────┐
                                       │ 403 → toast("Permission denied: MQTT_MAPPING_MANAGE")
                                       │ success → onSuccess: invalidateQueries([mqttMappings,
                                       │             mqttMappingThresholds, mqttReadings, mqttStatus,
                                       │             systemStatus])
                                       └──────────────────────
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/types.ts` | Modify | Append `MqttRawDeviceResponse`, `MqttRawMetricResponse`, `MqttMappingResponse`, `MqttMappingThresholds`, `MqttMappingStatus`, `MqttRuntimeStatus` interfaces. |
| `frontend/services/queryKeys.ts` | Modify | Append factories: `mqttDevices()`, `mqttDeviceMetrics(deviceId)`, `mqttReadings({limit})`, `mqttStatus()`, `mqttMappings({status})`, `mqttMappingThresholds(mappingId)`. |
| `frontend/services/queryResources.ts` | Modify | Append `fetchMqttDevices / Metrics / Readings / Status / Mappings / Thresholds` (signal-bearing, `as const`-typed) and `createMqttMapping / updateMqttMapping / approveMqttMapping / revokeMqttMapping / updateMqttMappingThresholds`. |
| `frontend/hooks/queries/useMqttQueries.ts` | Create | `useMqttDevicesQuery`, `useMqttDeviceMetricsQuery(deviceId, {enabled})`, `useMqttReadingsQuery({limit, refetchInterval})`, `useMqttStatusQuery({refetchInterval: 5000})`, `useMqttMappingsQuery({status})`, `useMqttMappingThresholdsQuery(mappingId, {enabled})`. |
| `frontend/hooks/queries/useMqttMutations.ts` | Create | `useCreateMqttMapping`, `useUpdateMqttMapping`, `useApproveMqttMapping`, `useRevokeMqttMapping`, `useUpdateMqttMappingThresholds` — each invalidates the keys listed in spec §Cache Invalidation. 403 → toast naming the missing permission via `toast.error("Permission denied: MQTT_MAPPING_MANAGE")` from `sonner`. |
| `frontend/components/MqttMonitoringPage.tsx` | Create | Tab host. Route-level guard (`hasPermission("MQTT_READ") \|\| hasPermission("ADMIN")`); `<Navigate to="/" replace/>` otherwise. Renders the four tabs. |
| `frontend/components/mqtt/MqttRawReadingsTab.tsx` | Create | Device list, expand-to-fetch-metrics, latest-readings panel. **Every reading row** renders `<RawNonKpiBadge classification kpiEligible />` from payload. |
| `frontend/components/mqtt/MqttMappingsTab.tsx` | Create | Status filter, table of `<MappingRow/>`, controls hidden unless `MQTT_MAPPING_MANAGE`. |
| `frontend/components/mqtt/MqttMappingForm.tsx` | Create | Create + edit (DRAFT only). Re-fetches latest mapping payload on open; submit sends full PUT. Inline errors per field. |
| `frontend/components/mqtt/MqttThresholdForm.tsx` | Create | Three inputs (operator, warning, critical). Disabled with tooltip unless status==APPROVED. 409 surfaces inline next to the offending input. |
| `frontend/components/mqtt/MqttBridgeStatusTab.tsx` | Create | Renders runtime flags + counters; "Running" / "Not Running" / "Not Configured" branches with `reason_code` and `last_error`. |
| `frontend/components/mqtt/MqttConfirmModal.tsx` | Create | Title, mapping identity (`id`, `target_ci_id`, `source_metric_name`), Cancel + Confirm buttons. Renders nothing else; Cancel closes without firing. |
| `frontend/components/mqtt/RawNonKpiBadge.tsx` | Create | Always renders the `classification` string and a `kpi_eligible=false` indicator. Defaults to `RAW_MQTT_NON_KPI` when payload fields missing/null (per spec §RAW_MQTT_NON_KPI Badge). |
| `frontend/App.tsx` | Modify | (a) Import `MqttMonitoringPage`; (b) add `<NavItem to="/monitoring/mqtt" icon="cell_tower" label="MQTT Monitoring"/>` wrapped in `{(hasPermission("MQTT_READ") \|\| hasPermission("ADMIN")) && (...)}`; (c) add `<Route path="monitoring/mqtt" element={<MqttMonitoringPage />}/>`. |
| `frontend/components/__tests__/MqttMonitoringPage.test.tsx` | Create | Vitest: 3 permission gating scenarios, non-KPI badge default, confirm-cancel issues no call, threshold disabled on DRAFT/REVOKED, 409 inline. |
| `frontend/test/e2e/mqtt-monitoring.spec.ts` | Create | Playwright: route to `/monitoring/mqtt`, stub `/mqtt/devices` + `/mqtt/mappings`, assert badge text, approve confirm flow, `systemStatus` invalidation via `waitFor`. |

## Permission Gates (where and how)

| Surface | Gate location | Behavior on deny |
|---------|--------------|------------------|
| Sidebar nav entry (`NavItem`) | `App.tsx` — `{(hasPermission("MQTT_READ") \|\| hasPermission("ADMIN")) && <NavItem/>}` | Entry does not render. |
| Route entry (`/monitoring/mqtt`) | Inside `MqttMonitoringPage.tsx` — `if (!hasPermission("MQTT_READ") && !hasPermission("ADMIN")) return <Navigate to="/" replace/>;` | Page renders nothing; no fetch fires (hooks never called). |
| Raw Readings tab body | Inside `MqttMonitoringPage.tsx` — reads inherit `MQTT_READ` from the page guard. | n/a (page already gated). |
| Mappings tab body | Same as Raw; Mappings tab is rendered for `MQTT_READ`. | Visible read-only. |
| "New Mapping", "Edit", "Approve", "Revoke", "Thresholds" controls | Inside `MqttMappingsTab.tsx` — `{(hasPermission("MQTT_MAPPING_MANAGE") \|\| hasPermission("ADMIN")) && (<button/>)}` | Controls do not render. |
| Mutation hook 403 | Inside each `useMqtt*Mutation` — `onError` → `toast.error("Permission denied: MQTT_MAPPING_MANAGE")`; prior list state untouched. | Toast appears; `queryClient` cache unchanged. |

`hasPermission` already returns `true` for `user.role === "ADMIN"` (see `AuthContext.tsx` lines 203–207). ADMIN bypass is therefore automatic; we still write it explicitly in the gate expressions to match existing conventions (`App.tsx` lines 139–158).

## State Management

**React Query keys** (added to `queryKeys.ts`):

```ts
mqttDevices: () => ["mqtt", "devices"] as const,
mqttDeviceMetrics: (deviceId: string | null) => ["mqtt", "devices", deviceId, "metrics"] as const,
mqttReadings: (params: { limit?: number } = {}) => ["mqtt", "readings", { limit: params.limit ?? 100 }] as const,
mqttStatus: () => ["mqtt", "status"] as const,
mqttMappings: (params: { status?: string } = {}) => ["mqtt", "mappings", { status: params.status ?? null }] as const,
mqttMappingThresholds: (mappingId: string | null) => ["mqtt", "mappings", mappingId, "thresholds"] as const,
```

**Defaults** (consistent with `index.tsx`):
- `staleTime: 5_000` (inherits QueryClient default).
- `refetchOnWindowFocus: false` (inherits).
- `refetchInterval`: latest-readings **5000ms**, Bridge Status **5000ms**, devices/mappings **none** (manual trigger on filter change).

**Cache invalidation** (post-mutation, per spec §Cache Invalidation):

```ts
const mqttInvalidate = (qc: QueryClient, kind: 'approve' | 'revoke' | 'mapping' | 'threshold') => {
  qc.invalidateQueries({ queryKey: ["mqtt", "mappings"] });
  qc.invalidateQueries({ queryKey: ["mqtt", "mappings", undefined, "thresholds"] });
  qc.invalidateQueries({ queryKey: ["mqtt", "readings"] });
  qc.invalidateQueries({ queryKey: ["mqtt", "status"] });
  if (kind === 'approve' || kind === 'revoke') {
    qc.invalidateQueries({ queryKey: ["system-status"] });   // KPI-derived refresh
  }
};
```

**Disabled query**: `useMqttDeviceMetrics(deviceId, { enabled: !!deviceId })` and `useMqttMappingThresholds(mappingId, { enabled: status === "APPROVED" })` to prevent fetching before row expansion or before APPROVED state.

## Safety Contract (encoded in tests)

1. **`RAW_MQTT_NON_KPI` badge always visible**: every reading row renders `<RawNonKpiBadge classification kpiEligible/>`. When payload fields are missing/null, badge defaults to `RAW_MQTT_NON_KPI` and shows `kpi_eligible=false`. No widget overlays the badge (z-index discipline + dedicated badge column).
2. **No "mark as KPI" affordance**: zero DOM nodes whose text matches `/Mark as KPI|Promote|Assign to KPI/i`. Verified by a single regex assertion over `document.body.textContent` in `MqttMonitoringPage.test.tsx`.
3. **Approve/revoke confirm modal**: modal renders `mapping_id`, `target_ci_id`, `source_metric_name` as `<dl>` rows; Cancel button closes modal; no mutation fires until Confirm is clicked.
4. **DRAFT-only edit**: edit button hidden unless `status==="DRAFT"`. Non-DRAFT rows show disabled "Edit (DRAFT only)" with tooltip "Editable only in DRAFT state".
5. **APPROVED-only threshold**: form inputs `disabled` with tooltip "Thresholds editable only on APPROVED mappings" for any `status !== "APPROVED"`.
6. **Partial-edit overwrite prevention**: opening the edit form triggers `GET /mqtt/mappings` (latest) and prefills; PUT sends full payload.
7. **403 from mutation**: `toast.error("Permission denied: MQTT_MAPPING_MANAGE")`; cache untouched; prior list state remains.

## Testing Strategy

| Layer | What to test | Approach |
|-------|-------------|----------|
| Vitest unit — query hooks | Each hook returns the expected key; 403 path toasts and leaves cache. | Mock `api` (per `MonitoringConsole.test.tsx` lines 16–22), wrap in `createTestQueryClient()`. |
| Vitest unit — `RawNonKpiBadge` | (a) Default-renders badge when fields missing; (b) renders API-supplied classification; (c) renders `kpi_eligible=false`. | `render()` + `screen.getByText`. |
| Vitest unit — `MqttConfirmModal` | Cancel button closes without firing; Confirm fires only after click; modal text includes the three identity fields. | Render with `vi.mocked(api.post).mockResolvedValue(...)`; assert call count. |
| Vitest unit — `MqttMappingForm` | DRAFT prefill works; PUT body is full payload; missing required fields show inline error and skip submit. | `fireEvent.submit` + assert `api.put` call shape. |
| Vitest unit — `MqttThresholdForm` | Inputs disabled when status≠APPROVED; tooltip present; 409 surfaces inline. | Drive status via prop; assert `disabled` attribute and `aria-invalid`. |
| Vitest integration — `MqttMonitoringPage` | 3 permission scenarios (READ allowed, READ denied, MANAGE allowed), badge default, no promotion control regex, confirm-cancel-no-call, 409-inline. | Full render with `MemoryRouter` + `AuthProvider` mock (`hasPermission` returns the per-test value). |
| Playwright E2E | Login → navigate to `/monitoring/mqtt` → see devices; click Approve → confirm modal → confirm → row status becomes APPROVED → `systemStatus` refetched. | `page.route` stub for `/mqtt/*` and `/system/status`; assert via `waitFor`. |

## Threat Matrix

This change has **no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary**. The application-level safety contract above (badge, no-promotion, confirm, DRAFT/APPROVED gating, 403 toast) is the relevant threat surface — captured in the **Safety Contract** section and propagated to Vitest tests unchanged.

| Boundary | Applicability |
|----------|---------------|
| Documentation-like paths | N/A — frontend code, not docs/CLI. |
| Git repo selection | N/A — no git ops in this change. |
| Commit state | N/A — orchestrator commits per delivery strategy. |
| Push state | N/A. |
| PR commands | N/A. |

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Raw row visually looks like a KPI | High | Permanent `<RawNonKpiBadge/>` on every reading; dedicated column with `bg-neutral-800` + `border-amber-500/30` (visually distinct from the green KPI badges elsewhere). RED test asserts badge text + DOM regex for "Mark as KPI". |
| Operator approves wrong mapping | Medium | `<MqttConfirmModal/>` shows `mapping_id` + `target_ci_id` + `source_metric_name`; Cancel closes without firing. RED test asserts `api.post` is never called on Cancel. |
| Stale cache after approve/revoke | Medium | All four `mqtt*` keys + `systemStatus` invalidated in `onSuccess` (per spec §Cache Invalidation). RED test asserts `queryClient` invalidation calls. |
| Partial-edit overwrite | Low–Med | Edit form re-fetches latest mapping before mount; PUT sends full payload built from re-fetch + form changes only on those fields. RED test asserts PUT body shape. |
| Threshold edit on non-APPROVED | Medium | Form disabled with tooltip outside APPROVED; 409 surfaces inline. RED test asserts both `disabled` and inline error message. |
| CI/MetricDef picker UX gap (reusing `/nodes` lists) | Medium | Acceptable per proposal §Risks: "reuse `/nodes` + `/metrics`; record gap". Captured as follow-up note in PR description; no code change here. |
| Concurrent `tab + invalidate` race | Low | No optimistic updates; we only invalidate on success. If mutation fails, cache stays at prior state, which is correct for audit. |

## Migration / Rollout

No migration. No DB changes. No backend deploy. Rollback = revert this branch (drop the `<NavItem>` and `<Route>` in `App.tsx`; remove `frontend/components/mqtt/*`). Optional feature flag: gate the route behind `VITE_MQTT_UI === "on"` for staged rollout — add a one-line guard in `MainLayout` if the operator team wants it.

## Open Questions

- None blocking. The CI/MetricDef picker gap is acknowledged in §Risks as a follow-up, not a design blocker.

## Reference endpoints (no changes)

All wired through `frontend/services/queryResources.ts` — read-only reference for the implementer:

| Method | Path | Body | Used by |
|--------|------|------|---------|
| GET | `/mqtt/devices` | — | Devices list |
| GET | `/mqtt/devices/{deviceId}/metrics` | — | Per-device metrics |
| GET | `/mqtt/readings?limit=N` | — | Latest readings panel |
| GET | `/mqtt/status` | — | Bridge Status tab |
| GET | `/mqtt/mappings?status=...` | — | Mappings list |
| POST | `/mqtt/mappings` | `MqttMappingCreateRequest` | Create draft |
| PUT | `/mqtt/mappings/{id}` | `MqttMappingUpdateRequest` (full payload) | Edit DRAFT |
| POST | `/mqtt/mappings/{id}/approve` | `{}` | Approve (gated, confirmed) |
| POST | `/mqtt/mappings/{id}/revoke` | `{}` | Revoke (gated, confirmed) |
| GET | `/mqtt/mappings/{id}/thresholds` | — | Prefill threshold form |
| PUT | `/mqtt/mappings/{id}/thresholds` | `MqttMappingThresholds` | Update thresholds |
