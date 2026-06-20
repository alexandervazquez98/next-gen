# PR0 Spec: DB-only `last_activity_at` Backfill

## Capability

- Creates/modifies: `auth-session-lifecycle`
- Modified capability diff: `auth-session-lifecycle` SHALL gain a deployment-safe DB repair step for legacy `refresh_tokens.last_activity_at IS NULL` rows before backend behavior changes.
- `audit-logging` diff: none in PR0.

## Code Evidence and Nullability Resolution

- `backend/models/refresh_token.py:24` declares `RefreshToken.last_activity_at` as ORM non-null.
- `backend/main.py:174` adds the DB column without `NOT NULL`; `backend/main.py:182` already backfills NULLs with `COALESCE(last_activity_at, created_at, NOW())`.
- Chosen path: keep the ORM non-null contract for #287 and treat NULL as transitional legacy DB state. Runtime/design SHALL use `COALESCE(last_activity_at, created_at)` semantics for reads/backfill, not “NULL until first request”. Broad nullable refactor remains out of scope.

## ADDED Requirements

### Requirement 1: Batched Backfill of Legacy Activity NULLs

The deployment SHALL update existing `refresh_tokens` rows where `last_activity_at IS NULL` in bounded batches around 1000 rows with a sleep between batches.

#### Scenario: Backfills at least one legacy row

- GIVEN a PostgreSQL `refresh_tokens` row with `last_activity_at IS NULL` and non-null `created_at`
- WHEN the PR0 backfill runs
- THEN that row SHALL have `last_activity_at` set to a non-null timestamp
- AND evidence SHALL identify at least one exercised live row.

#### Scenario: Empty batch is safe

- GIVEN no `refresh_tokens.last_activity_at IS NULL` rows exist
- WHEN the PR0 backfill runs
- THEN it SHALL complete without changing auth behavior or failing deployment.

### Requirement 2: DB-only Slice Boundary

PR0 MUST NOT change login, refresh, logout, audit, or frontend runtime behavior.

#### Scenario: No auth behavior changes ship in PR0

- GIVEN PR0 is reviewed independently
- WHEN its diff is inspected
- THEN only DB backfill/support artifacts SHALL be present
- AND backend/frontend session behavior SHALL remain unchanged.

## Test Plan

- Test file: `backend/tests/test_auth_service_refresh.py` or a dedicated backend migration/backfill test file created in PR0.
- Focused command: `uv run pytest backend/tests/test_auth_service_refresh.py -v` or `uv run pytest backend/tests/test_<backfill_file>.py -v`.
- Green means: RED test proves NULL rows exist before backfill, GREEN proves batched update fills them, plus PostgreSQL live-row evidence is attached.
- Slice-ready command: run the focused command first, then the full backend suite with the project backend test command.

## Out of Scope

- No `record_session_activity` implementation.
- No frontend idle/logout changes.
- No broad ORM/DB nullable mismatch refactor beyond transitional NULL handling.
- TODO post-#287: create issue “Fix stale-recovery rate-limit follow-up from Bug 3” — track proposal Bug 3 and `openspec/changes/fix-multi-window-session-timeout/verify-report-pr2.md:56-57` terminal-detail/rate-limit branch follow-up.

## Risks

- Live PostgreSQL evidence may require a seeded non-empty `refresh_tokens` table.
- If PR0 is skipped, PR1 idle expiry must still handle NULL via `COALESCE(last_activity_at, created_at)` to avoid immortal legacy sessions.
