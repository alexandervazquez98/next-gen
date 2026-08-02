# Proposal: Event Root Affected Exposure (P2 of fix #416)

## Intent

Surface the `affected_ci_ids` and `affected_count` metadata that the P0 two-pass correlation (PRs #417 + #418) already writes on every ROOT Event, so the Monitoring Console stops counting raw N+1 rows and operators see "X root events affecting Y CIs" — the contract described in issue #416 slices B and C.

## Scope

### In Scope (this change)

- **API surface**
  - `backend/models/core.py`: `EventFeedSummary` gains `affected_ci_ids: list[str] = Field(default_factory=list)` and `affected_count: int = 0`. Additive; no fields removed.
  - `backend/services/event_service.py`:
    - `_public_event_summary` allowlist extended with the two new keys.
    - `get_events(status: str = "CONSOLE", include_children: bool = False)` adds a Cypher `WHERE e.correlation_type = 'ROOT'` predicate when `include_children=False`.
    - New `get_affected_siblings(event_id)` returning a list of `{ci_id, ci_name, status}` records via `UNWIND` over the ROOT's `affected_ci_ids`.
  - `backend/routers/events.py`:
    - `GET /api/events` accepts `?include_children=true|false` (default `false`). `response_model_exclude_none=True` ensures empty fields are omitted from JSON.
    - New `GET /api/events/{event_id}/affected` with `EVENT_VIEW` permission parity.

- **Frontend surface**
  - `frontend/types.ts`: `EventSummary` and `EventDetailEvent` gain the two optional fields.
  - `frontend/services/queryKeys.ts`: `activeEvents({ include_children })` factory discriminates by the flag.
  - `frontend/services/queryResources.ts` + `frontend/hooks/queries/useActiveEventsQuery.ts`: thread `include_children` end-to-end.
  - `frontend/hooks/queries/useAffectedCIsQuery.ts`: originally proposed, removed during remediation (orphan hook). The Monitoring Console keeps its inline `useQueries` drill-down invocation.
  - `frontend/hooks/useEventCorrelation.ts`: adds `CONNECTS_TO` to the upstream grouping vocabulary (kept `DEPENDS_ON|HOSTED_ON` for backward compat).
  - `frontend/components/MonitoringConsole.tsx`: KPI counter now counts `isRoot` rows; sub-label "affecting N CIs" = sum of `affected_count` over those roots. Drill-down modal opens on click.

- **Consumer migration**
  - `backend/services/ai_chat_service.py:422`: passes `include_children=True` explicitly so the AI chat context still sees the raw child rows it relies on.

- **Tests (strict-TDD, 1028 authored lines)**
  - Backend: `test_event_service.py` (5 new tests for filter + drill-down + exclude_none contract), `test_routers_events.py` (4 endpoint tests + 2 exclude_none tests).
  - Frontend: Vitest for hooks, query keys, KPI reshape, modal flow, smoke mocks, CONNECTS_TO regression, type assertions.
  - Playwright e2e: `monitoring-event-kpi.spec.ts` exercises the modal drill-down (CI smoke lane runs it; local Docker not available).

- **Documentation**
  - CHANGELOG `[Unreleased]` entry under `### Fixed` and `### Changed` documenting the new API contract and the documented breaking default.

### Out of Scope (deferred follow-ups)

- P1: legacy in-process collector parity (`backend/services/snmp_service.py`).
- P3: leased queue writer parity (`backend/polling/event_writer.py`), topology backfill, AP parent synthesis, relationship remediation.
- WebSocket push for real-time KPI updates.
- Refactor of the inline `useQueries` drill-down into a reusable hook (was removed during remediation; reuse can come later if duplication reappears).
- Re-ingestion tooling for legacy PROPAGATED rows that pre-date the P0 deployment (covered by the archived `recommend-legacy-event-backfill` change).

## Capabilities

### New Capabilities

- `event-root-affected-exposure`: canonical capability covering the additive API contract (`affected_ci_ids`/`affected_count` on `EventFeedSummary`, `?include_children` filter, `GET /api/events/{id}/affected`, Monitoring KPI root-only counting + "affecting N CIs" sub-label).

### Modified Capabilities

- `event-write-time-correlation` (from P0): unchanged. The P0 writer at `backend/engines/snmp_worker.py:_update_propagated_root_events` continues to write the two fields; P2 only exposes what P0 already persisted.

## Approach

Two-pass derivation continued from P0:

1. **Backend serialization layer**: Pydantic surface → allowlist → query param → Cypher predicate → drill-down endpoint, in that order. Default flip is the only contract change; everything else is additive.
2. **Frontend rendering layer**: query-key discriminator → hook propagation → KPI reshape → drill-down modal, in that order. `useEventCorrelation` extends grouping vocabulary without removing the existing relationships.

## Affected Areas

- `backend/models/core.py` (Modified): additive `affected_ci_ids`/`affected_count`.
- `backend/services/event_service.py` (Modified): allowlist + filter + drill-down.
- `backend/routers/events.py` (Modified): query param + new endpoint + exclude_none.
- `backend/services/ai_chat_service.py` (Modified): explicit `include_children=True` for AI chat context.
- `frontend/types.ts` (Modified): optional fields on `EventSummary`.
- `frontend/services/queryKeys.ts` (Modified): `activeEvents({include_children})` factory.
- `frontend/services/queryResources.ts` (Modified): `fetchActiveEvents({include_children})`.
- `frontend/hooks/queries/useActiveEventsQuery.ts` (Modified): propagates the flag.
- `frontend/hooks/queries/useMonitoringConsoleData.ts` (Modified): accepts root-only payload.
- `frontend/hooks/useEventCorrelation.ts` (Modified): adds `CONNECTS_TO` to grouping.
- `frontend/components/MonitoringConsole.tsx` (Modified): KPI root-only counting + "affecting N CIs" sub-label + drill-down modal.
- `backend/tests/test_event_service.py` (Modified): strict-TDD matrix.
- `backend/tests/test_routers_events.py` (Modified): endpoint + exclude_none tests.
- `frontend/components/__tests__/MonitoringConsole.test.tsx` (Modified): KPI root filter test.
- `frontend/components/__tests__/MonitoringConsole.smoke.test.tsx` (Modified): smoke mock alignment.
- `frontend/components/__tests__/EventDetailModal.acceptance.test.tsx` (Modified): affected mock.
- `frontend/hooks/useEventCorrelation.test.ts` (Modified): CONNECTS_TO regression.
- `frontend/hooks/queries/resourceQueries.test.tsx` (Modified): query-key discriminator + dual-client cache isolation.
- `frontend/services/queryKeys.test.ts` (Modified): key discriminator unit.
- `frontend/test/e2e/monitoring-event-kpi.spec.ts` (New): Playwright modal flow.
- `CHANGELOG.md` (Modified): `[Unreleased]` entry.

## Risks

- **Documented breaking change**: `GET /api/events?status=CONSOLE` default now returns ROOT events only. Consumers that relied on raw N+1 rows must opt in via `?include_children=true`. The CHANGELOG and PR body call this out; `ai_chat_service` was migrated in commit `92d6f80`.
- **Legacy PROPAGATED rows**: events created before the P0 deployment still exist in Neo4j with `correlation_type=PROPAGATED`. They are invisible under the new default filter; the archived `recommend-legacy-event-backfill` change covers them separately.
- **Two sources of truth for `isRoot`**: backend `correlation_type` is authoritative; client `useEventCorrelation.isRoot` is a documented safety net. Documented in the design.
- **Empty-fields contract**: `response_model_exclude_none=True` on `GET /events` widens the JSON wire format — legacy clients that asserted `metric_id is None` now see absent keys. Documented; one frontend test was updated to align (`commit 3a0563a`).
- **Budget breach**: 1580 insertions vs. 800 budget (1.98×). Size-exception explicitly approved by the maintainer before apply.
- **Playwright e2e coverage**: cannot run locally without Docker daemon. The Vitest SCN-008 KPI test covers the same behavior at the React tree level; CI smoke lane runs the Playwright spec.

## Rollback Plan

Revert the merge commit. No DB migration. P0 writer continues to populate `affected_ci_ids`/`affected_count` on every ROOT Event — neither the writer nor the schema changes.

## Success Criteria

- [x] REQ-001..009 implemented and green in pytest.
- [x] SCN-001..010 implemented and green in pytest/vitest.
- [x] P0 invariants preserved (writer untouched, `affected_ci_ids` still written idempotently).
- [x] `GET /api/events/{id}/affected` idempotent (two consecutive calls return identical payload).
- [x] Query-key discriminator prevents cache cross-contamination between `include_children=true` and `false`.
- [x] Monitoring KPI shows root-only count + "affecting N CIs" sub-label.
- [x] `useEventCorrelation` groups across `DEPENDS_ON|HOSTED_ON|CONNECTS_TO`.
- [x] `?include_children=true` escape hatch for AI/audit/legacy consumers.
- [x] CHANGELOG entry under `[Unreleased]` with breaking change documented.

## Linked Artifacts

- Spec: `openspec/specs/event-root-affected-exposure/spec.md` (canonical) + `openspec/changes/archive/<date>-fix-416-event-amplification-p2/specs/event-root-affected-exposure/spec.md` (delta).
- Exploration: `openspec/changes/archive/<date>-fix-416-event-amplification-p2/exploration.md`.
- Design: `openspec/changes/archive/<date>-fix-416-event-amplification-p2/design.md`.
- Tasks: `openspec/changes/archive/<date>-fix-416-event-amplification-p2/tasks.md`.
- Verify: `openspec/changes/archive/<date>-fix-416-event-amplification-p2/verify-report.md`.
- Source issue: `alexandervazquez98/next-gen#416`.
- Prior art (P0 archive): `openspec/changes/archive/2026-07-29-fix-416-event-amplification/`.
