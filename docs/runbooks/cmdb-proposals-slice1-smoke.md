# CMDB Proposals — Slice 1 Smoke Runbook

> **Audience**: on-call reviewer who just merged the Slice 1 PR
> (storage + service + repo + permission seed).

This runbook proves the Slice 1 deliverables are live in Neo4j and that no
existing test is regressed. Run after each deploy.

## Pre-flight

1. Confirm `FEATURE_CMDB_PROPOSALS_ENABLED` is **off** (default for this slice).
   Slice 1 does not wire HTTP routes; setting it to `true` before Slice 2
   merges will 404 every endpoint.
2. Confirm the venv you test under has `backend/.venv` populated and the
   migrations directory is on disk.

## Steps

### 1. Migration applies without error

```bash
cd backend
NE4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... \
  ../backend/.venv/bin/python -c "
from database import get_db
driver = get_db()
with driver.session() as session:
    session.run('CREATE CONSTRAINT ci_proposal_id_unique IF NOT EXISTS FOR (p:CIProposal) REQUIRE p.id IS UNIQUE')
    session.run('CREATE INDEX ci_proposal_status IF NOT EXISTS FOR (p:CIProposal) ON (p.status)')
    session.run('CREATE INDEX ci_proposal_created_at IF NOT EXISTS FOR (p:CIProposal) ON (p.created_at)')
    session.run('CREATE INDEX ci_proposal_category IF NOT EXISTS FOR (p:CIProposal) ON (p.proposed_category)')
print('migration applied')
"
```

### 2. No orphan `:CIProposal` rows exist

```bash
cd backend
../backend/.venv/bin/python -c "
from database import get_db
driver = get_db()
with driver.session() as session:
    result = session.run('MATCH (p:CIProposal) RETURN count(p) AS n').single()
    n = result['n'] if result else 0
    assert n == 0, f'expected 0 :CIProposal rows, got {n}'
    print('graph clean: 0 :CIProposal rows')
"
```

### 3. Pytest slice 1 modules are green

```bash
cd backend
../backend/.venv/bin/pytest \
  tests/test_ai_permissions.py \
  tests/test_seed_roles_cmdb.py \
  tests/test_migration_005_ci_proposal_schema.py \
  tests/test_models_cmdb_proposal.py \
  tests/test_cmdb_proposal_repo.py \
  tests/test_audit_redaction.py \
  tests/test_cmdb_proposal_service.py \
  tests/test_cmdb_proposal_ttl_sweep.py \
  -q
```

Expected: **all green** (50+ tests in total).

### 4. Seed script is idempotent

Run it twice; the second invocation must NOT change role grants:

```bash
cd backend
NE4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... \
  ../backend/.venv/bin/python -m seed_roles
# Re-run — should print "Skipping system role … — already up to date" for each role.
NE4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... \
  ../backend/.venv/bin/python -m seed_roles
```

### 5. TTL sweep dry-run

```bash
cd backend
NE4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... \
  ../backend/.venv/bin/python -m scripts.cmdb_proposal_ttl_sweep --retention-days 30
# Should print "No stale DRAFT proposals to revoke." when no proposals exist.
```

### 6. Verify the docs guide is reachable

```bash
test -f docs/ai/cmdb-proposals.md && echo "guide present"
grep -q 'POST /api/cmdb/proposals' docs/ai/cmdb-proposals.md && echo "endpoints documented"
```

## Pass criteria

- All six steps above produce the expected output.
- No regressions in any previously-green pytest module
  (`pytest -q` should report no new failures).

If any step fails, revert the Slice 1 PR; the `:CIProposal` label is additive
and can be removed with a one-off Cypher if needed:

```cypher
MATCH (p:CIProposal) DETACH DELETE p;
DROP CONSTRAINT ci_proposal_id_unique IF EXISTS;
DROP INDEX ci_proposal_status IF EXISTS;
DROP INDEX ci_proposal_created_at IF EXISTS;
DROP INDEX ci_proposal_category IF EXISTS;
```