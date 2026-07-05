# Design: Validate Legacy Backfill Smoke Fixtures

## Technical Approach

Run the smoke validation from a clean worktree checked out at `origin/main` / `v1.13.9` or later, because the dirty root is on `fix/pingcheck-packet-loss` and the required CLI files are only verified on `origin/main`. Use the existing shared local Neo4j stack documented in `docs/worktree-test-environment.md`, managed by `scripts/shared-test-env.sh`, `docker-compose.test-env.yml`, and `config/test-env/worktree-host.sample`. Do not read denied `.env` files; source approved exports or copy the sample in the clean worktree only.

The validation seeds minimal, marker-scoped `Event` nodes, runs the existing read-only audit/recommendation pipeline, validates expected buckets, persists evidence under this change, and deletes all marked records in `finally`/`trap` cleanup.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Execution checkout | Require clean worktree at `origin/main` / `v1.13.9+` before touching local data. | Use dirty root. | Prevents unrelated branch changes from contaminating evidence and guarantees `backend/scripts/audit_legacy_event_discriminators.py` exists. |
| Environment | Reuse shared local Neo4j at `bolt://127.0.0.1:17687`. | Start new Docker/test DB. | Scope explicitly forbids new environments; the shared stack is already documented. |
| Fixture shape | Directly create tagged `Event` records with `issue155_smoke=true`, `issue155_smoke_run_id`, stable `id`, `ci_id`, `metric_id`, `status`, `severity`, `message`, discriminator fields, and timestamps. | Use polling writer paths. | The classifier query reads `Event` properties directly and only optionally joins `(:CI)-[:HAS_EVENT]->(e)`. Minimal nodes reduce cleanup risk. |
| Classification validation | Use existing service functions for marker rows plus existing CLI reports for pipeline smoke. | Trust aggregate CLI recommendation only. | Current CLI supports `--limit` but no marker filter, and recommendation JSON has bucket counts but no per-record ids. Per-fixture validation needs marker extraction or direct classifier reuse. |

## Data Flow

```
clean worktree + approved env
  -> seed tagged Event fixtures
  -> run CLI audit/recommendation read-only
  -> extract/compute smoke-only classifications
  -> compare expected buckets and Markdown/JSON parity
  -> cleanup marked records and verify zero remain
  -> write evidence files
```

Known classifier triggers from `backend/services/legacy_event_discriminator_audit.py`:
- safe: fully populated `event_type`, `failure_family`, and `source_protocol`, with no ambiguity trigger.
- ambiguous: missing discriminator plus message/source hints for collection failure, timeout, ICMP/PING availability, threshold, breached, host down, or availability.
- no-touch: non-ambiguous missing discriminator findings, e.g. populated `event_type="THRESHOLD"` with missing `failure_family` and no ambiguous text.

## File Changes

| File | Action | Description |
|---|---|---|
| `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/` | Create | Store run manifest, seeded fixture plan, CLI stdout/stderr, Markdown/JSON reports, validation summary, and cleanup proof. |
| `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/validate_smoke_fixtures.py` | Create | Local-only evidence runner that seeds, validates, and cleans up marker-scoped fixtures. |
| `openspec/changes/validate-legacy-backfill-smoke-fixtures/design.md` | Create | This design. |

## Interfaces / Contracts

Fixture contract:
- every fixture MUST include `issue155_smoke=true` and unique `issue155_smoke_run_id`.
- expected bucket map MUST include `safe_candidates`, `ambiguous_records`, and `no_touch_records`.
- cleanup query MUST delete only records matching both marker fields, then verify `MATCH (e:Event {issue155_smoke:true, issue155_smoke_run_id:$run_id}) RETURN count(e)` is zero.

CLI contract:
- run `python backend/scripts/audit_legacy_event_discriminators.py --report audit --format json --output ...` for record-level finding evidence.
- run `python backend/scripts/audit_legacy_event_discriminators.py --report recommendation --format json|markdown --output ...` for existing pipeline evidence.
- if smoke IDs are absent from audit JSON because CLI lacks marker filtering, mark the run invalid and record the filter gap.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Expected bucket derivation for seeded rows | Add focused tests around fixture definitions and classifier output if helper logic is committed. |
| Integration/manual evidence | Shared Neo4j seed/report/cleanup flow | Run evidence helper from clean worktree using approved sample/export env. |
| Consistency | Markdown/JSON report parity | Compare counts, schema version, bucket labels, confidence, and finding codes. |

## Migration / Rollout

No migration required. This is local evidence only and does not authorize production mutation or production-scale safety claims.

## Open Questions

- [ ] Whether to upstream a CLI marker filter later; current design treats the missing filter as a validation gap to record, not a blocker to safe cleanup.
