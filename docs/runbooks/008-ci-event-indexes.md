# Runbook: CI/Event Neo4j Index Migration (feat-523-ci-event-neo4j-indexes)

Operational runbook for applying `008_ci_event_indexes.cypher` to a live Neo4j
instance. This is a **one-time schema operation**; it does not run on every deploy.

## What it does

Creates five index/constraint objects on the `:CI` and `:Event` labels:

| Name | Type | Target |
|---|---|---|
| `ci_id_unique` | UNIQUE CONSTRAINT | `:CI.id` |
| `event_id_unique` | UNIQUE CONSTRAINT | `:Event.id` |
| `event_ci_id` | INDEX | `Event.ci_id` |
| `event_metric_id` | INDEX | `Event.metric_id` |
| `ci_status` | INDEX | `CI.status` |

These unblock index-seek plans on the two hottest write paths in the system:
`topology_repo.py:66` (`MERGE (n:CI {id})`) and `event_writer.py:439`
(event dedup on `{ci_id, metric_id}`).

## Preflight — MUST run before applying

The uniqueness constraints **fail on import** if duplicate IDs already exist. The
`:CI.id` and `:Event.id` columns have never had a database-level uniqueness
enforcement — only application-level MERGE convention — so drift is possible.

Run both queries against the target Neo4j **before** applying the migration:

```cypher
// Check for duplicate :CI.id values
MATCH (c:CI)
WITH c.id AS id, count(*) AS n
WHERE n > 1
RETURN id, n
LIMIT 20;

// Check for duplicate :Event.id values
MATCH (e:Event)
WITH e.id AS id, count(*) AS n
WHERE n > 1
RETURN id, n
LIMIT 20;
```

**If either query returns rows**: the migration will abort. Resolve the
duplicate IDs first (deduplicate or delete the colliding rows) before
re-running the preflight. No schema changes are applied when duplicates are
found.

## How to apply

Run from the repository root INSIDE the backend container:

```bash
docker compose exec -T backend python scripts/migrate_ci_event_indexes.py
```

Exit codes:

| Code | Meaning |
|---|---|
| `0` | All statements applied (or already present) |
| `1` | Preflight failure — duplicate IDs detected; nothing applied |
| `2` | Statement execution error — migration aborted partway |

The script is idempotent. Every statement uses `IF NOT EXISTS`, so re-runs
are safe.

## How to verify

After a successful apply, confirm the constraints and indexes exist:

```cypher
SHOW CONSTRAINTS YIELD name, entityType, propertyType, isNodeConstraint
WHERE name STARTS WITH 'ci_id_' OR name STARTS WITH 'event_id_'
RETURN name, entityType, propertyType, isNodeConstraint;

SHOW INDEXES YIELD name, entityType, properties, indexType
WHERE name STARTS WITH 'event_ci_id'
   OR name STARTS WITH 'event_metric_id'
   OR name STARTS WITH 'ci_status'
RETURN name, entityType, properties, indexType;
```

Expected: `ci_id_unique` and `event_id_unique` as node uniqueness constraints on
`id`; `event_ci_id` and `event_metric_id` as range indexes on `ci_id` and
`metric_id`; `ci_status` as a range index on `status`.

## This is a one-time step

The Neo4j data directory (`./docker/neo4j/data`) is a host bind mount, so it
**persists across rebuilds and restarts**. Once applied, the constraints and
indexes survive container restarts and `docker compose down/up` cycles.

Do **not** re-run this migration on every deploy. Running it on a database
that already has the constraints is safe (it is idempotent), but it is
unnecessary noise in deployment logs.

## When it WOULD need re-running

This migration would need to be re-applied only after a **data-only restore**
that carried no schema. The project has two backup paths:

- **`apoc.export.all` in `scripts/pre-rebuild-backup.sh`** — online export
  via APOC. This exports data only; it does **not** include schema (constraints
  or indexes). After a restore from this path, re-run `migrate_ci_event_indexes.py`.

- **`neo4j-admin database dump`** — offline, full database export that **does**
  include schema. A restore from this path preserves the constraints and indexes
  automatically. No re-run needed.

If unsure which backup path was used, run the verification query above. If the
constraints are absent, re-run the migration.

## Rollback

All statements use `IF NOT EXISTS` — there is no automatic rollback. To drop
the constraints and indexes by hand:

```cypher
DROP CONSTRAINT ci_id_unique IF EXISTS;
DROP CONSTRAINT event_id_unique IF EXISTS;
DROP INDEX event_ci_id IF EXISTS;
DROP INDEX event_metric_id IF EXISTS;
DROP INDEX ci_status IF EXISTS;
```

The `IF EXISTS` form is safe to run even when the object is not present.

## References

- Issue: #523
- Migration file: `backend/migrations/008_ci_event_indexes.cypher`
- Applier script: `backend/scripts/migrate_ci_event_indexes.py`
- Test: `backend/tests/test_migration_008_ci_event_indexes.py`
- SDD change: `openspec/changes/feat-523-ci-event-neo4j-indexes/`
