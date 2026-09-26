// Migration 007: User.aggregate_breakdown_regions (per-user scope for #391 PR1).
//
// Per-user scope for the ``graph:aggregate_breakdown:read`` capability introduced
// by #391 PR1 (cmdb-graph-lod-runtime OpenSpec change). Separating capability
// (permission) from scope (per-user region list) lets operators assign
// city-level aggregate breakdown to specific regions without granting global
// breakdown.
//
// All statements are IF NOT EXISTS / SET defaults so the migration is idempotent
// and can be re-applied on every cold start.
//
// Ownership: cmdb-graph-lod-runtime (#391 PR1)
// Rollback one-liner (manual, only if migration is reverted):
//   No DROP needed for the Neo4j property; existing rows carry null which the
//   service treats as [] (empty list, global breakdown). Postgres column drop
//   requires: ALTER TABLE users DROP COLUMN aggregate_breakdown_regions;

// Neo4j: add the property if absent (no-op on subsequent runs).
// (:User) nodes gain a ``aggregate_breakdown_regions`` property defaulting
// to an empty list. Existing rows: no backfill needed; the service treats
// missing/empty as "no scope" (same effect as []).

// Postgres: add the column if absent.
ALTER TABLE users ADD COLUMN IF NOT EXISTS aggregate_breakdown_regions TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];