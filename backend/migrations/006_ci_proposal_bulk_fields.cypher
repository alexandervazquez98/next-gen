// PR feat-489 Slice 1B: add bulk-manifest metadata to :CIProposal.
//
// Existing rows pre-#489 carried only `ci` (single) in `manifest_json`.
// This migration backfills `manifest_mode` and `ci_count` on those rows
// so the read path can dispatch single vs bulk without re-parsing the
// manifest JSON on every read. New rows from PR #489 set both fields
// at create time.
//
// All statements are idempotent. Existing rows get `manifest_mode = "single"`
// and `ci_count = 1` (the legacy default); bulk proposals created after
// #489 land with their actual values.
//
// Ownership: feat-489 (issue #489, PR slice 1B)
// Rollback one-liner:
//   The two SETs are no-ops on rows where the fields are already absent
//   after a backup restore; safe to leave the migration applied.

// Backfill manifest_mode for rows that don't have it yet.
// Single mode is the legacy default; bulk proposals always have cis[] so
// they get caught by the cis-detection branch above.
MATCH (p:CIProposal)
WHERE p.manifest_mode IS NULL
SET p.manifest_mode =
    CASE
        WHEN p.manifest_json IS NOT NULL AND toLower(p.manifest_json) CONTAINS '"cis"'
            THEN 'bulk'
        ELSE 'single'
    END;

// Backfill ci_count for rows that don't have it yet.
MATCH (p:CIProposal)
WHERE p.ci_count IS NULL
SET p.ci_count = 1;

// Index on manifest_mode so the proposal list can filter chat/csv/mcp
// without a full scan once the Source column in ProposalsCmdbPage starts
// reading it (T4.11 lands the UI use; the index is safe to add now).
CREATE INDEX ci_proposal_manifest_mode IF NOT EXISTS
FOR (p:CIProposal) ON (p.manifest_mode);
