// PR feat-443-physical-link-polling: cache last_polled_at on :PhysicalLink.
//
// Slice 4/4 of the fiber-optic / physical-link visualization chain (#443).
// The polling bridge (backend/polling/physical_link_bridge.py) writes
// ``pl.last_polled_at`` whenever at least one endpoint of the link has a
// fresh ``metric_values`` row. This column is a *cache* only — the
// single source of truth for actual sample data is still
// ``metric_values`` (no parallel state representation per spec).
//
// Why each statement (query evidence from code exploration):
//   pl.last_polled_at — nullable datetime cache; the bridge writes a
//                        timestamp; the absence of a value (null) reads
//                        as "never polled yet" on dashboards. The field
//                        is intentionally NOT required so existing rows
//                        (slice 1/2 data) keep their shape unchanged.
//   physical_link_last_polled_at — supporting index. The bridge
//                        filters by status IN {UP, UNKNOWN, PLANNED}
//                        and writes by id; the read path (dashboards)
//                        may want to sort by last_polled_at DESC, so
//                        the index is on (last_polled_at).
//
// Idempotency:
//   Every statement uses IF NOT EXISTS so the migration can be re-applied
//   safely. The SET ... = null is also a no-op on re-run (the field is
//   already null for rows that have not been polled yet).
//
// Hard constraints (from #443 body):
//   - Do NOT modify the existing tunnel `medium` field.
//   - Do NOT change the slice-3 read model (this column is additive
//     only).
//   - metric_values remains the single source of truth.
//
// PREFLIGHT (recommended before applying to a live database):
//   :PhysicalLink is the slice-1 node label. No data is at risk: the
//   new column is nullable and the SET ... = null is a no-op for any
//   row that has not yet been touched by the bridge.
//     MATCH (pl:PhysicalLink) RETURN count(pl), count(pl.last_polled_at);
//
// Ownership: feat/443-physical-link-polling
// Rollback one-liner:
//   DROP INDEX physical_link_last_polled_at IF EXISTS;
MATCH (pl:PhysicalLink)
SET pl.last_polled_at = null;

CREATE INDEX physical_link_last_polled_at IF NOT EXISTS
FOR (pl:PhysicalLink) ON (pl.last_polled_at);
