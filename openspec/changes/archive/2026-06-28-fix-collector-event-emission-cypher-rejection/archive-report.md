# Archive Report — fix-collector-event-emission-cypher-rejection

## Status

**Archive status:** PASS (APPROVED-WITH-NOTES by `sdd-verify`; no CRITICAL findings at archive time; 2 previously CRITICAL findings now resolved in commit `f955dd2`).

**Archived on:** 2026-06-28
**Main / tracker SHA at archive:** `14faff7`
**Issue:** `alexandervazquez98/next-gen#340`
**PR:** `alexandervazquez98/next-gen#341` (`fix/340-cypher-param-fallback` @ `eded8fd`) — OPEN at archive time, left for the user to merge.

## Goal

Preserve Event emission when production Neo4j rejects collector-attributed Event writes with `Neo.ClientError.Statement.SyntaxError: Variable poll_collector_id not defined`, by adding a narrow helper-level fallback that retries the write without the parameter and logs diagnostic context, while keeping the primary collector-attributed path unchanged.

## References

- Issue: `alexandervazquez98/next-gen#340` — `Neo.ClientError.Statement.SyntaxError: Variable poll_collector_id not defined` silently drops ~30+/hour of Availability / Collection Failure Events.
- PR: `alexandervazquez98/next-gen#341` — `fix/340-cypher-param-fallback`.
- Sibling: `openspec/changes/fix-event-duplication-cross-writer/` (introduced the `poll_collector_id` attribution pattern; still active, owns the canonical `event-deduplication` root spec).
- Production reference: `nexgen_snmp_worker` on `10.53.1.22`, built 2026-06-28 07:17:46 UTC.

## Artifacts read

- `openspec/changes/fix-collector-event-emission-cypher-rejection/proposal.md`
- `openspec/changes/fix-collector-event-emission-cypher-rejection/specs/cypher-param-fallback/spec.md` (NEW capability)
- `openspec/changes/fix-collector-event-emission-cypher-rejection/specs/event-deduplication/spec.md` (DELTA, deferred — see "Capabilities modified")
- `openspec/changes/fix-collector-event-emission-cypher-rejection/design.md`
- `openspec/changes/fix-collector-event-emission-cypher-rejection/tasks.md`
- `openspec/changes/fix-collector-event-emission-cypher-rejection/verify-report.md` (APPROVED-WITH-NOTES)
- `openspec/changes/fix-collector-event-emission-cypher-rejection/apply-progress.md` (pulled from PR worktree `fix-collector-event-emission-cypher-rejection@eded8fd`)
- `openspec/changes/fix-event-duplication-cross-writer/specs/event-deduplication/spec.md` (active upstream capability)
- `openspec/specs/ci-workflow-lint-cleanliness/spec.md` (format reference for the `## Source` trailer)
- `openspec/changes/archive/2026-06-20-fix-287-session-keep-alive/archive-report.md` (format reference)
- `openspec/config.yaml`

## Capabilities added

### `cypher-param-fallback` (NEW)

Promoted to root: `openspec/specs/cypher-param-fallback/spec.md`.

Six requirements lifted verbatim from the change's delta spec, then re-shaped
to the canonical `### Requirement: <name>` form (no frontmatter) per the
`ci-workflow-lint-cleanliness` precedent:

| # | Requirement |
|---|---|
| 1 | Specific undefined-parameter trigger |
| 2 | Fallback writes Event without collector parameter |
| 3 | Non-matching Cypher errors propagate |
| 4 | Protected Event writer coverage (5 call sites: 3 in `backend/engines/snmp_worker.py` + 2 in `backend/services/snmp_service.py`) |
| 5 | Diagnostic observability (`cypher-param-fallback` ERROR marker) |
| 6 | Error path is visible, not silent |

The root spec carries a `## Source` trailer pointing back to the archived
change folder and a `## Companion delta (deferred)` section that flags the
deferred `event-deduplication` merge for the next archive phase.

## Capabilities modified

### `event-deduplication` (DELTA — DEFERRED)

The change carried an `## ADDED Requirements` delta on the `event-deduplication`
capability (`Defense-in-depth fallback preserves deduplication` with three
scenarios). The root `openspec/specs/event-deduplication/spec.md` does not yet
exist; the canonical version lives in the still-active change
`openspec/changes/fix-event-duplication-cross-writer/specs/event-deduplication/spec.md`.

**Action taken:** the delta is preserved in this archive folder as audit
trail but was NOT merged into root specs. The merge is the responsibility of
the next `fix-event-duplication-cross-writer` archive phase. Until that
archive lands, callers should read both:

- `openspec/changes/fix-event-duplication-cross-writer/specs/event-deduplication/spec.md` (canonical content)
- `openspec/changes/archive/2026-06-28-fix-collector-event-emission-cypher-rejection/specs/event-deduplication/spec.md` (this change's delta, not yet merged)

This is a structural limitation of the current archive ordering, not a
specification defect. The upstream change should record the delta in its
`archive-report.md` and append the new requirement to the canonical
`openspec/specs/event-deduplication/spec.md` during its archive.

## Out-of-scope calls preserved from the proposal

These were explicitly excluded in `proposal.md` and remain out of scope at archive time:

- Deduplication changes from `fix-event-duplication-cross-writer` / issue #322.
- Topology RCA wiring from #310.
- Structural refactor of `engines/snmp_worker.py` or `services/snmp_service.py`.
- Backfill for silently dropped Events.
- Migration of `engines/snmp_worker.py` to the lease/polling path under `backend/polling/`.
- Operator runbook for fallback attribution (deferred per `design.md` §"Affected Areas" — added as a follow-up task on the next cycle).

## Task completion / reconciliation

- The persisted `tasks.md` artifact on the main worktree still carries `- [ ]` (pre-apply) acceptance sub-checkboxes. The `sdd-apply` phase executed on the PR worktree (`/home/alex/dev/next-gen/worktrees/fix-collector-event-emission-cypher-rejection`) and never rewrote the main-worktree tasks file.
- `sdd-verify` proof backs the reconciliation: 16/16 targeted tests PASS, full backend suite delta is `+3 passed, 0 new failures` (the 148 pre-existing failures on `main` are unchanged per `comm -23 branch_failures main_failures`). 9/9 spec scenarios PASS in the Spec↔Test Traceability table.
- This is the **stale-checkbox reconciliation** path from the `sdd-archive` skill: the orchestrator's structured status (`tasks ✅`, `verifyReport ⚠️ APPROVED WITH NOTES`) and the verify-report's runtime evidence together prove every unchecked code/test task is complete.
- **Reconciliation action taken:** the 12 code/test acceptance sub-checkboxes in `tasks.md` have been flipped from `- [ ]` to `- [x]` and a reconciliation header was added at the top of the archived `tasks.md` explaining the path. The 7 remaining `- [ ]` boxes are the **operator-driven** tasks (Task 4.2: rebuild image + restart worker on `10.53.1.22`; Task 4.3: production log verification via `docker logs ... | grep cypher-param-fallback`; Task 4.4: post-merge `gh issue close 340`); per `apply-progress.md` these were explicitly SKIPPED/DEFERRED by the user and are not part of the SDD code-change audit trail.
- 11/11 implementation tasks (1.1–4.4) are tracked; Tasks 1.1–3.B + Task 4.1 are code/test tasks (12 acceptance sub-checkboxes, all `[x]`). Tasks 4.2, 4.3, 4.4 (deploy, log verify, issue close) are operator-driven and remain `[ ]` by design.

## Spec ↔ Test Traceability (preserved from verify-report)

| Spec scenario / requirement | Covering test(s) | Runtime status |
|---|---|:---:|
| `cypher-param-fallback`: Matching production rejection triggers fallback | `test_matching_client_error_triggers_fallback_and_logs`; worker/service fallback tests | PASS |
| `cypher-param-fallback`: Availability down Event survives primary rejection | `test_icmp_availability_falls_back_on_poll_collector_id_undefined`; `test_fallback_query_has_no_dangling_commas` | PASS |
| `cypher-param-fallback`: Different syntax error is not retried | `test_non_matching_client_error_reraises_without_fallback`; worker non-matching tests | PASS |
| `cypher-param-fallback`: All affected writers use fallback guard | 3 worker fallback tests + 2 service fallback tests | PASS |
| `cypher-param-fallback`: Operator can count fallback incidents | `test_matching_client_error_triggers_fallback_and_logs` | PASS |
| `cypher-param-fallback`: Cycle continues with visible failure evidence | Helper + writer fallback tests | PASS |
| `event-deduplication`: Fallback creates canonical Event under lock | `test_lock_acquired_before_session_run_in_fallback_path`; source inspection | PASS (deferred merge) |
| `event-deduplication`: Concurrent writers remain serialized during fallback | `test_lock_acquired_before_session_run_in_fallback_path` | PASS (deferred merge) |
| `event-deduplication`: Happy path remains collector-attributed | `test_primary_success_skips_fallback`; source inspection | PASS (deferred merge) |

## Mechanical Cypher Validity Check (preserved from verify-report)

Regex used against each extracted `fallback_query` string:

```text
r',\s*}\s*$'      # trailing comma before closing brace on a line
r',\s*MERGE\b'    # trailing comma before MERGE
r',\s*WITH\b'     # trailing comma before WITH
r',\s*RETURN\b'   # trailing comma before RETURN
```

| Writer site | Trailing comma before `}` | Before `MERGE` | Before `WITH` | Before `RETURN` | Verdict |
|---|---:|---:|---:|---:|---:|
| `snmp_worker.py:360` collection failure fallback | No | No | No | No | PASS |
| `snmp_worker.py:486` ICMP availability fallback | No | No | No | No | PASS |
| `snmp_worker.py:644` ICMP latency fallback | No | No | No | No | PASS |
| `snmp_service.py:553` existing Event SET fallback | No | No | No | No | PASS |
| `snmp_service.py:647` new Event CREATE fallback | No | No | No | No | PASS |

## Validation / sync evidence

- PR #341 cumulative diff: 7 files, +1582 / -32 (over the 400-line review budget; labelled `size:exception`).
- Targeted test command: `uv run python -m pytest backend/tests/test_neo4j_write_guard.py backend/tests/test_snmp_worker_cypher_fallback.py backend/tests/test_snmp_service_cypher_fallback.py -v` → 16 passed, 1 warning in 1.00s.
- Full backend suite (post `f955dd2`): 1206 passed, 148 failed, 1 skipped. The 148 failures are pre-existing on `main` (RTU routers, MQTT subscriber, dictionary service, router auth, RTU integration, subscriber e2e per issue #267); `comm -23` against the main-baseline failure set is empty.
- No `Co-Authored-By` / AI attribution trailers in any of the 3 work-unit commits.
- Conventional commit titles only; PR uses the project-required `uv run python -m pytest` runner.

## PR state (audit trail)

| SHA | Message |
|-----|---------|
| `ac7cfcd` | `fix(collector): harden Event writers with cypher-param-fallback (#340)` |
| `f955dd2` | `fix(collector): build fallback query without dangling commas; tighten predicate (#340)` |
| `eded8fd` | `docs(sdd): track apply-progress.md for fix-collector-event-emission-cypher-rejection (#340)` |

PR #341 was left OPEN at archive time. The user merges it; deploy + log verification are operator-driven (see "Deployment plan" below).

## Discoveries worth surfacing

These are preserved in the archive because they show how **naive `string.replace()` on Cypher is unsafe** and what the right shape of the fix is. Future SDD changes that touch Cypher generation should read this section.

1. **Naive `string.replace()` on Cypher leaves dangling commas in SET clauses.** The first apply (`ac7cfcd`) constructed the fallback query by running `.replace("poll_collector_id: $poll_collector_id", "")` and `.replace("poll_collector_id = $poll_collector_id", "")` on the primary query. Because `poll_collector_id` is rarely the last property in a `SET` clause or row-dict, the removal left a stray trailing comma in 4 of 5 protected sites. The fallback Cypher was itself invalid; the mock tests asserted absence of `poll_collector_id` but did NOT assert Cypher validity. The fix (`f955dd2`) replaces the helper-side `replace()` with **explicit per-writer `fallback_query` string constants** — duplication is intentional to eliminate any ambiguity about the resulting Cypher. The mechanical regex check in the verify-report (`r',\s*}\s*$'`, `r',\s*MERGE\b'`, etc.) is now a regression guard.

2. **`str(error)` is not the same as `error.message` for `neo4j.exceptions.ClientError`.** The first predicate checked `"poll_collector_id" in str(error) and "not defined" in str(error)`. It worked in production but it was broader than `design.md` §8 specified. The Neo4j Python driver exposes the server's rejection text on `error.message`; `str(error)` formats that with a code prefix (`{code: Neo.ClientError.Statement.SyntaxError} {message}`). Reading `.message` is the only reliable way to detect the specific "Variable X not defined" rejection without false positives from unrelated errors whose formatted string happens to mention X. Fix: `is_poll_collector_id_undefined_error` now reads `error.message` and `isinstance(error, _CLIENT_ERROR_CLASS)`. The captured-class trick (`_CLIENT_ERROR_CLASS = neo4j.exceptions.ClientError` at module load) is also necessary because `conftest.py` replaces `sys.modules['neo4j']` with a `MagicMock`, and `isinstance(error, neo4j.exceptions.ClientError)` would otherwise raise `TypeError: isinstance() arg 2 must be a type, a tuple of types, or a union`.

3. **Mock session raising pattern: fail-then-succeed needs a "raised once" flag.** The first version of the worker/service tests had the mock raise on EVERY matching call, causing the fallback call (which also matches the query marker) to raise again and fail the test. The standard pattern is to track a `raised["done"] = True` flag in the mock and only raise on the FIRST matching call. This is now the documented convention for fail-then-succeed mock scenarios in this project.

4. **Module-alias double-import breaks test fixtures.** Production code uses `from services.neo4j_write_guard import ...` (relative path from `backend/`), but tests use `from backend.services.neo4j_write_guard import ...` (absolute). Python loads these as two distinct module objects in `sys.modules` even though they share the same `.py` file — they have independent `__dict__` instances. A `monkeypatch.setattr(backend.services.X, "attr", val)` does NOT affect `services.X.attr`. The fixture must patch BOTH aliases. The same pattern applies to `backend.services.event_lock` (used in `test_writer_advisory_lock.py`).

5. **Test isolation: record the primary call BEFORE raising.** In the `snmp_service` tests, the mock replaced `session.run` with a wrapper that called `original_run(query, **params)` and THEN decided whether to raise. Calling `original_run` first records the query in `session.queries`; without that, the primary attempt would be invisible and the test could not prove the fallback was actually triggered.

6. **`testcontainers` env gap is pre-existing on `main`.** The 4 `test_writer_advisory_lock.py` tests that need `from testcontainers.postgres import PostgresContainer` fail with `ModuleNotFoundError` because `testcontainers` is not in the uv dev-dependencies. This is unrelated to PR #341 (pre-existing on `ac7cfcd`), but a follow-up could add `testcontainers[postgres]` to `backend/requirements-dev.txt` if these tests need to run in CI.

## Deployment plan (operator handoff, from `verify-report.md`)

1. **Rebuild image.**
   ```bash
   docker compose -f /home/alex/nextgen/docker-compose.yml build nextgen-snmp-engine
   ```
2. **Restart worker.**
   ```bash
   docker compose -f /home/alex/nextgen/docker-compose.yml up -d nexgen_snmp_worker
   ```
   (Or the prod overlay variant on `10.53.1.22`.)
3. **Verify fallback marker.**
   ```bash
   docker logs -f nexgen_snmp_worker | grep cypher-param-fallback
   ```
   Expected behaviour post-fix: zero occurrences if Neo4j now accepts `$poll_collector_id` again; populated only if the unresolved hypothesis is still active — in which case Events stop being silently dropped.
4. **After 24h, close issue #340.**
   ```bash
   gh issue close 340 --comment "Fixed via #341; helper + 8 writer wirings shipped. Verified via docker logs ... | grep cypher-param-fallback on 10.53.1.22."
   ```

## Operator runbook (deferred)

The proposal calls for an operator runbook documenting the fallback attribution trade-off; per `design.md` §"Affected Areas" this is explicitly **deferred** until after the operator handoff completes. The runbook should land in `docs/runbooks/cypher-param-fallback.md` in a follow-up cycle, not in this change.

## Blockers / approvals

- No archive blockers remain. `verify-report.md` is `APPROVED-WITH-NOTES` (no CRITICAL); the 2 previously CRITICAL findings were addressed in `f955dd2` with runtime evidence and a mechanical regression test.
- The PR `size:exception` label is a process note, not a blocker.
- The deferred `event-deduplication` merge is a structural limitation of archive ordering, not a spec defect, and is preserved with a clear "Companion delta (deferred)" pointer on the new `cypher-param-fallback` root spec.
- No destructive merge approval was needed (the new root spec is purely additive; no prior `cypher-param-fallback` content existed).
- No same-domain active change collision was reported (the only other writer that touches `event-deduplication` is the upstream `fix-event-duplication-cross-writer`, which is explicitly waiting for this archive to land first).

## Archived path

- Source: `openspec/changes/fix-collector-event-emission-cypher-rejection/`
- Target: `openspec/changes/archive/2026-06-28-fix-collector-event-emission-cypher-rejection/`
- Archive type: date-prefixed audit folder (per `openspec-convention.md`).

## Files in the archive

- `proposal.md` (5,084 bytes)
- `design.md` (6,814 bytes)
- `tasks.md` (16,370 bytes, post-reconciliation checkboxes flipped)
- `verify-report.md` (7,694 bytes, APPROVED-WITH-NOTES)
- `apply-progress.md` (20,777 bytes, pulled from PR worktree @ `eded8fd`)
- `archive-report.md` (this file)
- `specs/cypher-param-fallback/spec.md` (delta preserved as audit trail)
- `specs/event-deduplication/spec.md` (delta preserved as audit trail; merge deferred to `fix-event-duplication-cross-writer` archive)

## Notes

- No product code or tests were edited during archive (only `openspec/` directories were touched).
- The `cypher-param-fallback` main spec is the source of truth for that capability; the delta under `specs/cypher-param-fallback/spec.md` in the archive is a snapshot, not a separate spec.
- The `event-deduplication` delta in this archive is **not** source of truth — it is an orphan delta waiting for the upstream change to absorb. The next `fix-event-duplication-cross-writer` archive should reference this archive's `specs/event-deduplication/spec.md` in its `## Companion delta` section.
