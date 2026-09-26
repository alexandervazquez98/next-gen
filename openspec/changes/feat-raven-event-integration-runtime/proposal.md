# Proposal: raven(event) integration runtime slices (#441, #445, #440)

## Problem

The Raven CMDB event integration epic (#196) is split into 4 slices:

1. **#442** (slice 1, approved) — alias/reference resolution for upstream CI IDs in Raven
2. **#441** (slice 2, this proposal) — stable JSON event export contract from next-gen
3. **#445** (slice 3, this proposal) — Raven normalizer + CLI ingest path
4. **#440** (slice 4, this proposal) — operator boundary for Raven event writes from external sources

Slice 1 (#442) defines how Raven canonical CI identity binds to upstream references (CI.id, ip, hostname, serial, mac). This proposal owns the runtime/spec slices 2-4: the export shape, the ingest pipeline, and the operator boundary.

Without these slices, Raven cannot consume next-gen events safely — there is no stable wire contract, no controlled write path, and no operator gate.

## Scope

### Owns

- **#441** — versioned JSON export contract for next-gen events to Raven; REST endpoint or CLI dump; documented schema with examples for OPEN / ACK / RECOVERED; backward-compat policy
- **#445** — Raven normalizer/bridge component: field mapping (next-gen → Raven), severity/status mapping, dedupe key `next-gen:<event.id>`, CLI `raven event ingest --source next-gen`; references resolve via #442 before any CI-specific persistence
- **#440** — operator boundary contract for Raven event writes from external sources: default dry-run/read-only, approval gate, audit row (actor, source, target event id, payload hash, timestamp, before/after); rejection requires free-text reason

### Does not own

- Raven CI identity / alias resolution (owned by #442 slice 1)
- Direct DB or model writes from external sources (forbidden by hard rule)
- next-gen mutations (ack, comment, close, run_diagnostic) from Raven (deferred until guardrails designed)
- Network protocol or transport between next-gen and Raven (HTTP REST + CLI stdin/file assumed)
- Auto-approval rules for any write path (must be explicit, versioned, reviewed)

## Approach

Three sequential slices, each as a PR with strict TDD:

```
#441 — JSON export contract
  PR1: schema + endpoint + 3 examples (OPEN/ACK/RECOVERED) + backward-compat doc

#445 — normalizer + CLI
  PR1: field mapping + dedupe + reference resolution via #442
  PR2: CLI `raven event ingest --source next-gen` + batch + partial failure

#440 — operator boundary
  PR1: approval gate + dry-run default + audit emission
  PR2: rejection-with-reason + audit row completeness
```

## Requirements

### From #441

1. Documented JSON schema with examples for OPEN, ACK, RECOVERED events
2. Backward-compatibility policy (additive within major, removals require new major)
3. Export surface: REST endpoint or CLI dump, suitable for `raven event ingest --source next-gen`
4. Required fields per event: `event.id`, `ci_ref` (at minimum `id`), `created_at`, `last_seen`, `severity`, `status`, `type`, `raw` (verbatim)
5. Existing `/api/events` shape must remain backward-compatible; export is additive

### From #445

1. Field mapping next-gen → Raven documented in spec
2. Dedupe key `next-gen:<event.id>` (stable per source)
3. Reference resolution via #442 before any CI-specific persistence
4. Unknown references fail ingest with typed error; no auto-create
5. CLI `raven event ingest --source next-gen --stdin | --file <path>`
6. Idempotent on dedupe key
7. Returns count + first error per batch on failure
8. No direct DB or model writes from external sources

### From #440

1. Default dry-run/read-only for all external writes
2. Approval gate per write
3. Audit row: actor, source, target event id, payload hash, timestamp, before/after state
4. Rejection requires free-text reason; reason becomes part of the audit row
5. Auto-approval rules (if any) explicit, versioned, reviewed
6. Operator UX surfaces recommendations similar to #154 stale-event reminders pattern

## Hard constraints

- No direct DB or model writes from external sources — only the validated Raven API/CLI may persist
- Reference resolution via #442 before any CI-specific persistence; no auto-create on unknown
- Audit row mandatory for every write or attempted write
- Export contract additive within major version; removals require new major
- next-gen mutations stay deferred until their own guardrails are designed

## Non-goals

- Bidirectional sync (Raven → next-gen)
- Webhook-based ingestion (HTTP REST + CLI stdin/file only)
- Authentication scheme between next-gen and Raven (separate concern)
- Schema evolution tooling (manual versioning only)
- Concurrent-write conflict resolution beyond dedupe key

## Affected files (rough)

### #441 next-gen export contract
- new: `backend/schemas/event_export.py` (or extend existing)
- new: `backend/routers/event_export.py` (or extend existing events router)
- new: `backend/tests/test_event_export_contract.py`
- new: `docs/itsm/event-export-contract.md` (schema documentation + examples + backward-compat policy)
- modify: existing events endpoints if needed for backward-compat

### #445 Raven normalizer + CLI
- new: `backend/services/raven_ingest_service.py` (or wherever Raven code lives)
- new: `backend/normalizers/next_gen_event_normalizer.py`
- new: `backend/cli/raven_event_ingest.py`
- new: `backend/tests/test_raven_ingest_normalizer.py`
- new: `backend/tests/test_raven_ingest_cli.py`

### #440 Raven operator boundary
- new: `backend/services/raven_operator_boundary.py`
- new: `backend/routers/raven_recommendations.py` (or extend existing)
- new: `backend/tests/test_raven_operator_boundary.py`
- new: `backend/tests/test_raven_audit_emission.py`

## Estimated footprint

| Slice | LOC estimate | Files | Review budget risk |
|---|---|---|---|
| #441 export | ~400 (1 PR) | 3 new + 1 modified | Low |
| #445 normalizer | ~800 (2 PRs) | 4 new | Low per PR |
| #440 boundary | ~700 (2 PRs) | 3 new | Low per PR |
| **Total** | **~1900** | **~11** | Low |

## Open decisions for the maintainer

1. **Raven code location** — is Raven code in this repo (`backend/` with `raven_*` prefix) or a separate Raven repo? Affects file paths.
2. **Authentication between next-gen and Raven** — bearer token, mTLS, signed JWT? Out of scope but worth documenting the assumption.
3. **Export transport** — HTTP REST endpoint or CLI dump only, or both? Spec mentions both; need to confirm.
4. **Audit row storage** — same audit service as `backend/services/audit_service.py` or separate Raven audit table?