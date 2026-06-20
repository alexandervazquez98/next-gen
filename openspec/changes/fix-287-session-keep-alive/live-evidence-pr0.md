# Live PostgreSQL Evidence — PR0 (`fix/287-db-backfill`)

Captured: 2026-06-20 (local dev environment, single Docker `timescale/timescaledb:2.15.0-pg16` container `nexgen_postgres`, host machine running script via `RUNNING_LOCALLY=true POSTGRES_HOST=localhost`).

## BEFORE — seeded rows

```sql
SELECT id, user_id, session_id, last_activity_at FROM refresh_tokens ORDER BY id;

 id | user_id | session_id |      last_activity_at
----+---------+------------+----------------------------
  1 |       1 | legacy-1   |                           -- NULL: target of backfill
  2 |       1 | live-2     | 2026-06-20 21:00:02.961832  -- control: already populated
```

## Run

```bash
RUNNING_LOCALLY=true POSTGRES_HOST=localhost \
  uv run python backend/scripts/backfill_refresh_token_activity.py
```

```
2026-06-20 14:05:15,727 [INFO] Refresh-token activity backfill updated 1 rows
backfill_refresh_token_activity updated 1 rows
```

## AFTER — exercised row

```sql
SELECT id, user_id, session_id, last_activity_at FROM refresh_tokens ORDER BY id;

 id | user_id | session_id |      last_activity_at
----+---------+------------+----------------------------
  1 |       1 | legacy-1   | 2026-06-20 21:05:15.622024  -- backfilled with DB NOW()
  2 |       1 | live-2     | 2026-06-20 21:00:02.961832  -- control row untouched
```

## Remaining NULLs

```sql
SELECT count(*) AS still_null FROM refresh_tokens WHERE last_activity_at IS NULL;

 still_null
------------
          0
```

## Idempotency

A second run of the same script with the same DB state updates `0` rows, confirming the bounded-batch loop exits cleanly once no NULL rows remain:

```bash
RUNNING_LOCALLY=true POSTGRES_HOST=localhost \
  uv run python backend/scripts/backfill_refresh_token_activity.py
```

```
2026-06-20 14:05:22,709 [INFO] Refresh-token activity backfill updated 0 rows
backfill_refresh_token_activity updated 0 rows
```

## Acceptance criterion

- [x] PR0 backfills live PostgreSQL `refresh_tokens.last_activity_at IS NULL` rows in batches, with evidence against at least one real row (id=1 above).
- [x] Control row (id=2) is NOT modified by the backfill.
- [x] Idempotency: running twice updates 0 rows on the second run.
- [x] Backfilled timestamp comes from DB `NOW()`, not the application host clock.
- [x] Script `python backend/scripts/backfill_refresh_token_activity.py --help` works without `psycopg2` installed (verified by `test_help_works_without_postgres_db_import` subprocess test).
