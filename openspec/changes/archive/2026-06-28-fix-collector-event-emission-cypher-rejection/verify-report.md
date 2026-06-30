# Verify Report — fix-collector-event-emission-cypher-rejection

## Summary

⚠️ **APPROVED WITH NOTES.** The 2 prior CRITICAL findings are addressed; targeted runtime tests pass 16/16; no new CRITICAL findings found.

## CRITICAL — Previous findings, current status

- **CRITICAL #1 — Fallback query construction left invalid Cypher.**
  - **Addressed:** Yes.
  - **Evidence:** fallback queries are now explicit `fallback_query` strings, not helper-side `.replace()` output.
    - `backend/engines/snmp_worker.py:360-397` — collection-failure fallback removes `poll_collector_id` and ends SET with `existing.source_protocol = row.source_protocol` before `MERGE`.
    - `backend/engines/snmp_worker.py:486-524` — availability fallback ends SET with `existing.availability_source = row.availability_source` before `MERGE`.
    - `backend/engines/snmp_worker.py:644-677` — latency fallback ends SET with `existing.root_cause_ci_id = coalesce(...)` before `MERGE`.
    - `backend/services/snmp_service.py:553-565` and `647-682` — service SET/CREATE fallbacks omit `poll_collector_id` without dangling separators.
  - **Runtime evidence:** `test_fallback_query_has_no_dangling_commas PASSED [ 43%]` and mechanical regex check below: 5/5 fallback strings PASS.

- **CRITICAL #2 — Predicate used `str(error)` instead of `error.message`.**
  - **Addressed:** Yes.
  - **Evidence:** `backend/services/neo4j_write_guard.py:81-85`:
    ```python
    return (
        isinstance(error, _CLIENT_ERROR_CLASS)
        and "poll_collector_id" in error.message
        and "not defined" in error.message
    )
    ```
  - **Runtime evidence:** `test_predicate_uses_error_message_attribute PASSED [ 37%]`.

## Other findings (CRITICAL / WARNING / SUGGESTION)

- **CRITICAL:** None.
- **WARNING:** PR #341 is now 7 files, **+1582 / -32**, still above the normal review budget; label `size:exception` is present.
- **WARNING:** Fresh detached worktree required `uv pip install -r requirements.txt -r requirements-dev.txt` before the supported `uv run python -m pytest ...` command could find pytest. After dependency sync, tests passed.
- **SUGGESTION:** Keep the mechanical fallback-query regex test; it directly guards the production failure mode.

## Spec ↔ Test Traceability

| Spec scenario / requirement | Covering test(s) | Runtime status | Notes |
|---|---|---:|---|
| `cypher-param-fallback`: Matching production rejection triggers fallback | `test_matching_client_error_triggers_fallback_and_logs`; worker/service fallback tests | ✅ PASS | Helper + all protected writer paths tested. |
| `cypher-param-fallback`: Availability down Event survives primary rejection | `test_icmp_availability_falls_back_on_poll_collector_id_undefined`; `test_fallback_query_has_no_dangling_commas` | ✅ PASS | Fallback query omits param and is comma-clean. |
| `cypher-param-fallback`: Different syntax error is not retried | `test_non_matching_client_error_reraises_without_fallback`; worker non-matching tests | ✅ PASS | Non-matching errors re-raise. |
| `cypher-param-fallback`: All affected writers use fallback guard | 3 worker fallback tests + 2 service fallback tests | ✅ PASS | 5 call sites covered. |
| `cypher-param-fallback`: Operator can count fallback incidents | `test_matching_client_error_triggers_fallback_and_logs` | ✅ PASS | Log marker `cypher-param-fallback` asserted. |
| `cypher-param-fallback`: Cycle continues with visible failure evidence | Helper + writer fallback tests | ✅ PASS | Fallback result returned after ERROR log. |
| `event-deduplication`: Fallback creates canonical Event under lock | `test_lock_acquired_before_session_run_in_fallback_path`; source inspection | ✅ PASS | Lock precedes primary and is not re-acquired between primary/fallback. |
| `event-deduplication`: Concurrent writers remain serialized during fallback | `test_lock_acquired_before_session_run_in_fallback_path` | ✅ PASS | Structural ordering regression test added. |
| `event-deduplication`: Happy path remains collector-attributed | `test_primary_success_skips_fallback`; source inspection | ✅ PASS | Primary params still include `poll_collector_id`. |

## Mechanical Cypher Validity Check

Regex used against each extracted `fallback_query` string:

```text
r',\s*}\s*$'      # trailing comma before closing brace on a line
r',\s*MERGE\b'    # trailing comma before MERGE
r',\s*WITH\b'     # trailing comma before WITH
r',\s*RETURN\b'   # trailing comma before RETURN
```

Additional checked patterns: `r',\s*OPTIONAL MATCH\b'` and `r',\s*$'` for trailing comma at query end.

| Writer site | Trailing comma before `}` | Before `MERGE` | Before `WITH` | Before `RETURN` | Verdict |
|---|---:|---:|---:|---:|---:|
| `snmp_worker.py:360` collection failure fallback | No | No | No | No | ✅ PASS |
| `snmp_worker.py:486` ICMP availability fallback | No | No | No | No | ✅ PASS |
| `snmp_worker.py:644` ICMP latency fallback | No | No | No | No | ✅ PASS |
| `snmp_service.py:553` existing Event SET fallback | No | No | No | No | ✅ PASS |
| `snmp_service.py:647` new Event CREATE fallback | No | No | No | No | ✅ PASS |

## Test Results

Command run in detached PR worktree `/tmp/opencode/next-gen-pr341/backend` after dependency sync:

```bash
uv run python -m pytest tests/test_neo4j_write_guard.py tests/test_snmp_worker_cypher_fallback.py tests/test_snmp_service_cypher_fallback.py -v 2>&1 | tee /tmp/pytest_verify.log
```

Excerpt:

```text
collected 16 items
tests/test_neo4j_write_guard.py::test_predicate_uses_error_message_attribute PASSED [ 37%]
tests/test_neo4j_write_guard.py::test_fallback_query_has_no_dangling_commas PASSED [ 43%]
tests/test_neo4j_write_guard.py::test_lock_acquired_before_session_run_in_fallback_path PASSED [ 50%]
tests/test_snmp_service_cypher_fallback.py::test_store_metric_result_create_event_path_falls_back PASSED [100%]
======================== 16 passed, 1 warning in 1.00s =========================
```

## PR Status

- **PR:** https://github.com/alexandervazquez98/next-gen/pull/341
- **State:** OPEN
- **Branch:** `fix/340-cypher-param-fallback`
- **HEAD:** `eded8fd6357deec8699d3325adeef1924c6077fe`
- **Commits on PR:**
  - `ac7cfcd` `fix(collector): harden Event writers with cypher-param-fallback (#340)`
  - `f955dd2` `fix(collector): build fallback query without dangling commas; tighten predicate (#340)`
  - `eded8fd` `docs(sdd): track apply-progress.md for fix-collector-event-emission-cypher-rejection (#340)`
- **Files:** 7
- **Diff:** +1582 / -32
- **Labels:** `size:exception`
- **`apply-progress.md`:** now in PR; `git log --stat HEAD -- .../apply-progress.md` shows `1 file changed, 402 insertions(+)` in `eded8fd`.

## Verdict

⚠️ **APPROVED WITH NOTES** — no CRITICAL findings remain; warnings are review/process notes, not blockers.

## Recommended Next Step

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
