# Apply Progress — category-technology-icons

## Scope

Feature slice PR 4 surface migration is complete on top of PR 1 + PR 2 + PR 3. Prior runs migrated `MassLinkEditor` CI candidate rows, `DependencyMiniMap` node rendering, `VisualRelationshipEditor` graph node rendering, `GlobalInventory` list/detail category chips, `CIDetailModal` header category rendering, `NetworkVisualizer` technology legend rendering, and `MonitoringConsole` event-stream/detail rendering to the shared `CategoryIcon` renderer. This verification/refactor run created an ignored local `.env` with mock-only values adapted from `.env.example`, started Neo4j/PostgreSQL/backend through Docker Compose, installed backend test dependencies only inside the running backend container, and completed task 1.5 focused backend verification. Full frontend verification passed again. Full backend verification executed in the container but failed on unrelated existing suites outside category technology icons. Task 4.3 is now complete under a maintainer-approved scoped verification exception for this category-icons PR slice; this is not a claim that the full backend suite is green.

## Changed files (cumulative):

- `backend/tests/test_routers_catalog.py`
- `backend/tests/test_node_service.py`
- `backend/tests/test_topology_repo_nodes.py`
- `backend/services/category_icons.py`
- `backend/models/core.py`
- `backend/services/catalog_service.py`
- `backend/routers/catalog.py`
- `backend/repositories/topology_repo.py`
- `backend/services/node_service.py`
- `frontend/types.ts`
- `frontend/services/queryResources.ts`
- `frontend/utils/categoryIcons.ts`
- `frontend/components/CategoryIcon.tsx`
- `frontend/utils/categoryIcons.test.ts`
- `frontend/components/CategoryIcon.test.tsx`
- `frontend/services/queryResources.test.ts`
- `frontend/components/CatalogManager.test.tsx`
- `frontend/components/CatalogManager.tsx`
- `frontend/components/HardwareCatalog.tsx`
- `frontend/components/MassLinkEditor.test.tsx`
- `frontend/components/MassLinkEditor.tsx`
- `frontend/components/DependencyMiniMap.test.tsx`
- `frontend/components/DependencyMiniMap.tsx`
- `frontend/components/VisualRelationshipEditor.test.tsx`
- `frontend/components/VisualRelationshipEditor.tsx`
- `frontend/components/GlobalInventory.test.tsx`
- `frontend/components/GlobalInventory.tsx`
- `frontend/components/CIDetailModal.test.tsx`
- `frontend/components/CIDetailModal.tsx`
- `frontend/components/NetworkVisualizer.test.tsx`
- `frontend/components/NetworkVisualizer.tsx`
- `frontend/components/__tests__/MonitoringConsole.smoke.test.tsx`
- `frontend/components/MonitoringConsole.tsx`
- `frontend/vite.config.ts`

## TDD Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1 | `frontend/utils/categoryIcons.test.ts`<br>`frontend/components/CategoryIcon.test.tsx` | Unit | N/A (new) | ✅ Written | ✅ Passed in this environment via `npm exec -- pnpm run test:run CategoryIcon.test.tsx categoryIcons.test.ts` | ✅ Covered multiple cases | ✅ Clean |
| 2.2 | `frontend/types.ts`, `frontend/services/queryResources.ts` | Unit | N/A (typing/API contract refactor) | N/A (typing/API contract refactor) | ✅ Passed in this environment via `npm exec -- pnpm run test:run categoryIcons CategoryIcon queryResources` | ➖ Not structurally branching | ➖ N/A |
| 2.3 | `frontend/utils/categoryIcons.ts`, `frontend/components/CategoryIcon.tsx` | Unit | N/A (new) | ✅ Written by 2.1 tests | ✅ Passed in this environment via focused icon tests | ✅ Behavior covered in `2.1` tests | ✅ Clean |
| 2.4 | `frontend/services/queryResources.test.ts` | Unit | ✅ Focused frontend primitive/queryResources suite passed before checklist update (17 tests) | ✅ Existing API contract tests cover `CategoryRecord.icon_key` parsing | ✅ Passed `npm exec -- pnpm run test:run categoryIcons CategoryIcon queryResources` (3 files, 17 tests) | ✅ Resolver/component/queryResources cases cover explicit keys, fallback, search, and API contract | ✅ No local duplicate category technology icon mappings found outside shared `frontend/utils/categoryIcons.ts` |
| 3.1 | `frontend/components/CatalogManager.test.tsx` | Integration/UI | Existing catalog tests available | ✅ Written before code | ✅ Passed previously via targeted `CatalogManager.test.tsx` | ✅ Covers current icon, searchable grid, preview, generic option, save payload | ✅ Clean |
| 3.2 | `frontend/components/CatalogManager.tsx`, `frontend/components/HardwareCatalog.tsx` | UI | Existing catalog tests available | ✅ Covered by 3.1 tests | ✅ Passed previously via targeted catalog tests | ✅ Uses shared `CategoryIcon` + icon catalog search utility | ✅ Clean |
| 3.3 | `frontend/components/CatalogManager.test.tsx` | Integration/UI | Existing catalog tests available | ✅ Selector state scope covered in 3.1 test additions | ✅ Passed `CatalogManager.test.tsx` (4 tests) | ✅ Selector state reset path verified | ✅ Clean |
| 4.1/4.2 partial — `MassLinkEditor` CI candidate rows | `frontend/components/MassLinkEditor.test.tsx` | Integration/UI | N/A — no existing focused `MassLinkEditor` test file before this slice | ✅ Two failing tests written first for explicit `category_icon_key` rendering, category-name fallback, and status separation | ✅ Passed `MassLinkEditor.test.tsx` (2 tests) after minimal implementation | ✅ Two cases: explicit router icon and Layer 2 switch fallback by category name | ✅ Focused icon tests passed with `CategoryIcon`/resolver coverage |
| 4.1/4.2 partial — `DependencyMiniMap` nodes | `frontend/components/DependencyMiniMap.test.tsx` | Integration/UI | ✅ Existing related `EventDetailModal.acceptance.test.tsx` passed before changes (41 tests) | ✅ Two failing tests written first for explicit `category_icon_key`, category-name fallback, and status separation | ✅ Passed `DependencyMiniMap.test.tsx` (2 tests) after minimal implementation | ✅ Two cases: explicit router icon and Layer 2 switch fallback by category name | ✅ Focused DependencyMiniMap + icon regression passed (52 tests) |
| 4.1/4.2 partial — `VisualRelationshipEditor` graph nodes | `frontend/components/VisualRelationshipEditor.test.tsx` | Integration/UI | ✅ Existing `VisualRelationshipEditor.test.tsx` passed before changes (30 tests) | ✅ Two failing tests written first for explicit `category_icon_key`, category-name fallback, and status separation | ✅ Passed `VisualRelationshipEditor.test.tsx` (32 tests) after minimal implementation | ✅ Two cases: explicit router icon and Layer 2 switch fallback by category name | ✅ Focused VisualRelationshipEditor + icon regression passed (41 tests) |
| 4.1/4.2 partial — `GlobalInventory` list/detail chips | `frontend/components/GlobalInventory.test.tsx` | Integration/UI | ✅ Existing `GlobalInventory.test.tsx` passed before changes (3 tests) | ✅ Two failing tests written first for explicit `category_icon_key`, category-name fallback, and status separation | ✅ Passed `GlobalInventory.test.tsx` (5 tests) after minimal implementation | ✅ Two cases: explicit router icon and Layer 2 switch fallback by category name | ✅ Focused GlobalInventory + icon regression passed (14 tests) |
| 4.1/4.2 completion — `CIDetailModal` header category chip | `frontend/components/CIDetailModal.test.tsx` | Integration/UI | N/A — no existing focused `CIDetailModal` test file before this slice | ✅ Two failing tests written first for explicit `category_icon_key`, category-name fallback, and status separation | ✅ Passed `CIDetailModal.test.tsx` (2 tests) after minimal implementation | ✅ Two cases: explicit router icon and Layer 2 switch fallback by category name | ✅ Focused CIDetailModal + icon regression passed (11 tests) |
| 4.1/4.2 partial — `NetworkVisualizer` technology legend | `frontend/components/NetworkVisualizer.test.tsx` | Integration/UI | N/A — no existing focused `NetworkVisualizer` test file before this slice | ✅ Two failing tests written first for explicit `category_icon_key`, category-name fallback, and status color separation | ✅ Passed `NetworkVisualizer.test.tsx` (2 tests) after minimal implementation | ✅ Two cases: explicit router icon and Layer 2 switch fallback by category name | ✅ Focused NetworkVisualizer + icon regression passed (11 tests) |
| 4.1/4.2 completion — `MonitoringConsole` event stream | `frontend/components/__tests__/MonitoringConsole.smoke.test.tsx` | Integration/UI | ✅ Existing `MonitoringConsole.smoke.test.tsx` passed before changes in prior slice (8 tests) | ✅ Two failing tests written first for explicit `category_icon_key`, category-name fallback, and status separation | ✅ Passed `MonitoringConsole.smoke.test.tsx` (10 tests) after minimal implementation | ✅ Two cases: explicit router icon and Layer 2 switch fallback by category name | ✅ Focused MonitoringConsole + icon regression passed (19 tests) |
| 4.1 audit fix — `MonitoringConsole` event-detail category strip | `frontend/components/__tests__/MonitoringConsole.smoke.test.tsx` | Integration/UI | ✅ Existing `MonitoringConsole.smoke.test.tsx` passed before changes (10 tests) | ✅ Two event-detail tests written first and failed before selector correction (Details accessible name mismatch), proving the missing path was not covered | ✅ Passed focused MonitoringConsole + icon regression (21 tests) with existing implementation; no production change required | ✅ Two cases: explicit router icon and Layer 2 switch fallback by category name; severity/status assertions stay separate | ✅ No implementation refactor needed; corrected test query to match actual accessible name |
| Test-only guard audit fix | `frontend/vite.config.ts` | Config | N/A — config guard only | ✅ Audit check identified missing explicit guard | ✅ Added `test.forbidOnly: true`; Vitest config accepted by focused run | ➖ Triangulation skipped: single structural guard option | ✅ No package script change needed |
| 1.5 | `backend/tests/test_routers_catalog.py`<br>`backend/tests/test_node_service.py`<br>`backend/tests/test_topology_repo_nodes.py` | Backend verification/refactor | ✅ Docker Compose backend environment created with mock `.env`; backend dev dependencies installed only inside the running backend container | N/A — verification/refactor task only | ✅ Passed `docker compose exec -T backend python -m pytest tests/test_routers_catalog.py tests/test_node_service.py tests/test_topology_repo_nodes.py` (117 tests) | ✅ Focused backend coverage includes catalog icon metadata/defaults/invalid rejection and `/nodes.type` compatibility with `category_icon_key` | ✅ No tracked backend refactor required; fallback behavior is centralized through `services.category_icons.resolve_category_icon` in the verified paths |
| 4.3 | Full frontend/backend verification with scoped backend exception | Full suite / scoped backend slice | ✅ Frontend full suite passed again (53 files, 461 tests); category-icons focused backend Docker verification passed (117 tests); backend full suite was runnable but not green | N/A — verification/refactor task only | ✅ Completed under maintainer-approved scoped verification exception: frontend passed and focused backend passed; full backend failed (101 failed, 947 passed, 1 skipped) in predominantly out-of-scope auth/events/RTU/dictionary/CLI suites | ✅ Backend failure triage recorded below; follow-up stabilization issue opened as #267 | ✅ Exception documented; no tracked code/test refactor required in this artifact-only update |

## Scoped Verification Exception — Task 4.3

Maintainer approval: The maintainer explicitly approved a scoped verification exception for task 4.3 on this category-icons PR slice.

This exception closes task 4.3 based on focused slice evidence while preserving that the full backend suite remains red. It is not a claim that backend full-suite verification is green.

Accepted verification evidence:
- Focused category-icons backend verification passed in Docker: `117 passed` for `tests/test_routers_catalog.py`, `tests/test_node_service.py`, and `tests/test_topology_repo_nodes.py`.
- Full frontend suite passed: `53 files / 461 tests`.
- Full backend suite remains red: `101 failed, 947 passed, 1 skipped`.
- Backend full-suite failures were triaged and are predominantly out-of-scope for category technology icons.
- One `test_routers_nodes.py` authentication-policy failure remains uncertain but unlikely related because this change touched node payload/icon metadata, not unauthenticated route policy, and focused node compatibility tests pass.

Follow-up stabilization tracking:
- GitHub issue #267: https://github.com/alexandervazquez98/next-gen/issues/267

## Issues / Deviations
- `corepack` is still unavailable in this environment, but `pnpm` is runnable through `npm exec -- pnpm`; focused frontend tests and the full frontend suite passed.
- Host Python still lacks `pytest`/`pip`; backend verification is now runnable through Docker Compose using mock-only `.env` values and container-local dev dependency installation.
- Full backend pytest is not green in this environment: `docker compose exec -T backend python -m pytest` failed with 101 failed, 947 passed, and 1 skipped. Failures are outside the category technology icon focused tests and include existing auth/events permission expectations, RTU/router 404s, dictionary service/repository mocks, CLI worker tests, and `HTTPException(..., code=...)` misuse in `routers/cis.py`. Task 4.3 is complete only under the maintainer-approved scoped verification exception tracked above.
- Triage rerun on 2026-06-14 reproduced the same full backend result with concise output: 101 failed, 947 passed, 1 skipped. The category-icons focused backend suite still passes in Docker: 117 passed for `tests/test_routers_catalog.py`, `tests/test_node_service.py`, and `tests/test_topology_repo_nodes.py`.
- Phase 4 task 4.1 is now checked accurately because `MonitoringConsole` covers both live event stream and event-detail category strip technology icon behavior.
- Phase 4 task 4.2 remains checked because `MonitoringConsole.tsx` already rendered `CategoryIcon` in both required places; this audit fix did not need production code changes.
- `frontend/vite.config.ts` now sets `test.forbidOnly: true` so focused tests cannot pass with committed `test.only`/`describe.only`.
- `DependencyMiniMap` renders the shared HTML `CategoryIcon` inside SVG via `foreignObject`; operational status text and colors remain separate from the technology icon.
- `VisualRelationshipEditor` uses `CategoryIcon` rendered to static markup inside SVG `foreignObject` nodes; operational status radius/stroke/fill remains separate from the technology icon.
- `GlobalInventory` renders technology icons in list/detail category chips while leaving critical/healthy metric indicators and warning symbols separate.
- `CIDetailModal` renders technology icons in the header category chip while leaving the operational status dot/text and metric warning/check indicators separate.
- `NetworkVisualizer` renders shared technology icons in a graph legend/list derived from visible graph nodes while keeping 3D node color/status handling separate.
- `MonitoringConsole` renders shared technology icons in the live event stream CI column and event-detail category strip while leaving severity/status badges and KPI status icons separate.

## Remaining
- No category-technology-icons apply tasks remain. Backend full-suite stabilization remains out of scope for this PR slice and is tracked in GitHub issue #267.

## Full Backend Failure Triage — 2026-06-14

Docker environment status: `neo4j`, `postgres`, and `backend` were running and healthy via `docker compose ps`; no containers were stopped. Full backend pytest was rerun inside the backend container with concise traceback output. `pytest-json-report` is not installed in the container, so `--json-report` was unavailable and no tracked artifacts were created.

| Test file/module | Failures | Likely cause | Category-icons assessment |
|---|---:|---|---|
| `tests/test_auth_extended.py` | 1 | Permission enum completeness drift. | Unrelated. |
| `tests/test_auth_router_refresh.py` | 2 | Cookie domain / secure flag expectations. | Unrelated. |
| `tests/test_cli_worker.py` | 34 | CLI worker helper expectations for regex extraction, credential fallback, escalation, and NaN rate limiting. | Unrelated. |
| `tests/test_dictionary_service.py` | 8 | Dictionary service mocked repository/CRUD contract mismatches. | Unrelated. |
| `tests/test_event_correlation.py` | 4 | Event correlation and recovery propagation expectations. | Unrelated. |
| `tests/test_polling_docs_links.py` | 2 | Polling documentation/link coverage expectations. | Unrelated. |
| `tests/test_routers_auth_users_roles.py` | 2 | Audit request context lacks `request.client` in TestClient scope for these cases. | Unrelated. |
| `tests/test_routers_dictionaries.py` | 1 | `routers/cis.py` raises `HTTPException(..., code=...)`, which FastAPI does not accept. | Unrelated. |
| `tests/test_routers_events.py` | 13 | Auth/guard behavior drift: expected 401/200/guard messages, got 403; some mocks patch missing `set_cooldown`. | Unrelated. |
| `tests/test_routers_links.py` | 4 | Link create/delete endpoints returning 403 where tests expect success/no auth block. | Unrelated. |
| `tests/test_routers_metrics_events.py` | 10 | Auth expectation drift on metrics/events routes: tests expect 401 for unauthenticated, got 403. | Unrelated. |
| `tests/test_routers_nodes.py` | 1 | Node list unauthenticated expectation drift: test expects 401, route returned 200. | Uncertain but unlikely related; category-icons changed node payload metadata, not router authentication policy. Focused `/nodes` compatibility tests pass. |
| `tests/test_rtu_integration.py` | 2 | RTU repository conversion error: `dict(record)` fails on mocked/driver record shape. | Unrelated. |
| `tests/test_rtu_sensor_repo.py` | 5 | Same RTU/sensor repository record conversion issue. | Unrelated. |
| `tests/test_rtus_router.py` | 12 | RTU/sensor router endpoints return 404 where tests expect mounted CRUD routes. | Unrelated. |

Changed backend paths comparison:
- Related changed paths (`backend/services/category_icons.py`, `backend/models/core.py`, `backend/services/catalog_service.py`, `backend/routers/catalog.py`, `backend/repositories/topology_repo.py`, `backend/services/node_service.py`) are covered by the focused Docker run and pass: 117 tests.
- No failures appear in `tests/test_routers_catalog.py`, `tests/test_node_service.py`, `tests/test_topology_repo_nodes.py`, or `tests/test_category_icons.py` in the full-suite summary.
- The only nearby full-suite failure is `tests/test_routers_nodes.py::TestGetNodes::test_list_nodes_unauthenticated`, but the observed failure is authentication policy (`200` vs expected `401`), not category/icon payload behavior.

Assessment: full backend failures are predominantly unrelated to category technology icons. One `/nodes` router authentication failure is classified as uncertain-but-unlikely-related because this change touched node payload metadata, while the failure concerns unauthenticated access behavior and focused node compatibility tests pass. Task 4.3 is complete under the maintainer-approved scoped verification exception documented above; backend full-suite stabilization remains tracked separately in GitHub issue #267.

## Test Commands Run
- `corepack --version` → failed (`corepack: command not found`).
- `npm exec -- pnpm --version` → passed (`10.12.1`).
- RED: `cd frontend && npm exec -- pnpm run test:run MassLinkEditor.test.tsx` → failed as expected before implementation (2 missing technology icon assertions).
- GREEN: `cd frontend && npm exec -- pnpm run test:run MassLinkEditor.test.tsx` → passed (2 tests).
- Focused icon regression: `cd frontend && npm exec -- pnpm run test:run MassLinkEditor.test.tsx CategoryIcon.test.tsx categoryIcons.test.ts` → passed (3 files, 11 tests).
- Safety net: `cd frontend && npm exec -- pnpm run test:run components/__tests__/EventDetailModal.acceptance.test.tsx` → passed (41 tests) before modifying `DependencyMiniMap.tsx`.
- RED: `cd frontend && npm exec -- pnpm run test:run DependencyMiniMap.test.tsx` → failed as expected before implementation (2 missing technology icon assertions).
- GREEN: `cd frontend && npm exec -- pnpm run test:run DependencyMiniMap.test.tsx` → passed (2 tests).
- Focused DependencyMiniMap regression: `cd frontend && npm exec -- pnpm run test:run DependencyMiniMap.test.tsx CategoryIcon.test.tsx categoryIcons.test.ts components/__tests__/EventDetailModal.acceptance.test.tsx` → passed (4 files, 52 tests).
- Safety net: `cd frontend && npm exec -- pnpm run test:run VisualRelationshipEditor.test.tsx` → passed before changes (30 tests).
- RED: `cd frontend && npm exec -- pnpm run test:run VisualRelationshipEditor.test.tsx` → failed as expected before implementation (2 missing technology icon assertions; 30 existing tests passed).
- GREEN: `cd frontend && npm exec -- pnpm run test:run VisualRelationshipEditor.test.tsx` → passed (32 tests).
- Focused VisualRelationshipEditor regression: `cd frontend && npm exec -- pnpm run test:run VisualRelationshipEditor.test.tsx CategoryIcon.test.tsx categoryIcons.test.ts` → passed (3 files, 41 tests).
- Safety net: `cd frontend && npm exec -- pnpm run test:run GlobalInventory.test.tsx` → passed before changes (3 tests).
- RED: `cd frontend && npm exec -- pnpm run test:run GlobalInventory.test.tsx` → failed as expected before implementation (2 missing technology icon assertions; 3 existing tests passed).
- GREEN: `cd frontend && npm exec -- pnpm run test:run GlobalInventory.test.tsx` → passed (5 tests).
- Focused GlobalInventory regression: `cd frontend && npm exec -- pnpm run test:run GlobalInventory.test.tsx CategoryIcon.test.tsx categoryIcons.test.ts` → passed (3 files, 14 tests).
- RED: `cd frontend && npm exec -- pnpm run test:run CIDetailModal.test.tsx` → failed as expected before implementation (2 missing technology icon assertions).
- GREEN: `cd frontend && npm exec -- pnpm run test:run CIDetailModal.test.tsx` → passed (2 tests).
- Focused CIDetailModal regression: `cd frontend && npm exec -- pnpm run test:run CIDetailModal.test.tsx CategoryIcon.test.tsx categoryIcons.test.ts` → passed (3 files, 11 tests).
- RED: `cd frontend && npm exec -- pnpm run test:run NetworkVisualizer.test.tsx` → failed as expected before implementation (2 missing technology icon assertions).
- GREEN: `cd frontend && npm exec -- pnpm run test:run NetworkVisualizer.test.tsx` → passed (2 tests).
- Focused NetworkVisualizer regression: `cd frontend && npm exec -- pnpm run test:run NetworkVisualizer.test.tsx CategoryIcon.test.tsx categoryIcons.test.ts` → passed (3 files, 11 tests).
- Safety net: `cd frontend && npm exec -- pnpm run test:run components/__tests__/MonitoringConsole.smoke.test.tsx` → passed before changes (8 tests).
- RED: `cd frontend && npm exec -- pnpm run test:run components/__tests__/MonitoringConsole.smoke.test.tsx` → failed as expected before implementation (2 missing technology icon assertions).
- GREEN: `cd frontend && npm exec -- pnpm run test:run components/__tests__/MonitoringConsole.smoke.test.tsx` → passed (10 tests).
- Focused MonitoringConsole regression: `cd frontend && npm exec -- pnpm run test:run components/__tests__/MonitoringConsole.smoke.test.tsx CategoryIcon.test.tsx categoryIcons.test.ts` → passed (3 files, 19 tests).
- Safety net: `cd frontend && npm exec -- pnpm run test:run components/__tests__/MonitoringConsole.smoke.test.tsx` → passed before audit-fix edits (10 tests).
- RED: `cd frontend && npm exec -- pnpm run test:run components/__tests__/MonitoringConsole.smoke.test.tsx` → failed after adding event-detail tests because the tests could not open the detail modal via exact accessible name `Details`; this exposed that the new assertions were on a previously uncovered path and needed selector correction, not production changes.
- GREEN: `cd frontend && npm exec -- pnpm run test:run components/__tests__/MonitoringConsole.smoke.test.tsx CategoryIcon.test.tsx categoryIcons.test.ts` → passed (3 files, 21 tests).
- `cd backend && python -m pytest tests/test_routers_catalog.py tests/test_node_service.py tests/test_topology_repo_nodes.py` → blocked (`/usr/bin/python: No module named pytest`). This is the repo-root-adjusted equivalent of the task command because running from `backend/` requires `tests/...` paths, not `backend/tests/...`.
- `cd frontend && npm exec -- pnpm run test:run categoryIcons CategoryIcon queryResources` → passed (3 files, 17 tests).
- `cd frontend && npm exec -- pnpm run test:run` → passed (53 files, 461 tests).
- `cd backend && python -m pip show pytest` → blocked (`/usr/bin/python: No module named pip`).
- `cd backend && python3 -m pytest tests/test_routers_catalog.py tests/test_node_service.py tests/test_topology_repo_nodes.py` → blocked (`/usr/bin/python3: No module named pytest`).
- `cd backend && python3 -m pip show pytest` → blocked (`/usr/bin/python3: No module named pip`).
- Created ignored local `.env` with mock-only values adapted from `.env.example`; no real secrets used.
- `docker compose ps` → initially no running services.
- `docker compose up -d neo4j postgres backend` → built backend image and started Neo4j, PostgreSQL, and backend services; Neo4j/PostgreSQL became healthy and backend started.
- `docker compose ps && docker compose exec -T backend python -m pip install -r requirements-dev.txt` → services running; installed `pytest`, `pytest-asyncio`, `httpx`, `pytest-cov`, and `factory-boy` only inside the running backend container.
- `docker compose exec -T backend python -m pytest tests/test_routers_catalog.py tests/test_node_service.py tests/test_topology_repo_nodes.py` → passed (117 tests, 17 warnings).
- `cd frontend && npm exec -- pnpm run test:run` → passed again (53 files, 461 tests).
- `docker compose exec -T backend python -m pytest` → failed outside this slice (101 failed, 947 passed, 1 skipped, 43 warnings); task 4.3 remained unchecked until the maintainer-approved scoped verification exception was recorded.
- `docker compose ps` → `neo4j`, `postgres`, and `backend` running and healthy.
- `docker compose exec -T backend python -m pytest -q --tb=short --disable-warnings --json-report --json-report-file=/tmp/backend-full-pytest-report.json` → blocked because `pytest-json-report` is not installed (`unrecognized arguments`).
- `docker compose exec -T backend python -m pytest -q --tb=short --disable-warnings` → reproduced full backend failure (101 failed, 947 passed, 1 skipped, 43 warnings); concise failure evidence captured in tool output, no tracked artifact created.
- Parsed the full pytest short summary by test file: 101 failures across 15 files/modules; none in category-icons focused test files.
- `docker compose exec -T backend python -m pytest -q --tb=short --disable-warnings tests/test_routers_catalog.py tests/test_node_service.py tests/test_topology_repo_nodes.py` → passed (117 tests, 17 warnings).
