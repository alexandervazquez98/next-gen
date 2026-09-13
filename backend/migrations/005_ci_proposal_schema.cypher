// PR feat-cmdb-ai-handoff: CMDB AI proposal lifecycle.
//
// Creates the :CIProposal label, its unique id constraint, and three indexes
// supporting the proposal review surface. All statements are IF NOT EXISTS so the
// migration is idempotent and can be re-applied on every cold start.
//
// Ownership: feat-cmdb-ai-handoff
// Rollback one-liner:
//   DROP CONSTRAINT ci_proposal_id_unique IF EXISTS;
//   DROP INDEX ci_proposal_status IF EXISTS;
//   DROP INDEX ci_proposal_created_at IF EXISTS;
//   DROP INDEX ci_proposal_category IF EXISTS;

CREATE CONSTRAINT ci_proposal_id_unique IF NOT EXISTS
FOR (p:CIProposal) REQUIRE p.id IS UNIQUE;

CREATE INDEX ci_proposal_status IF NOT EXISTS
FOR (p:CIProposal) ON (p.status);

CREATE INDEX ci_proposal_created_at IF NOT EXISTS
FOR (p:CIProposal) ON (p.created_at);

CREATE INDEX ci_proposal_category IF NOT EXISTS
FOR (p:CIProposal) ON (p.proposed_category);