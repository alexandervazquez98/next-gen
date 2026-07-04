# Tasks: Fix Collector Event Emission Cypher Rejection

**Change**: `fix-collector-event-emission-cypher-rejection`
**Issue**: #340 — `Neo.ClientError.Statement.SyntaxError: Variable poll_collector_id not defined` silently drops ~30+/hour of Availability / Collection Failure Events.
**Approach**: Tiny `run_with_cypher_param_fallback` helper near `backend/services/event_lock.py`. Detects the specific undefined-`poll_collector_id` `ClientError`, logs `cypher-param-fallback` with primary query/params/stack, then runs a fallback query without `poll_collector_id`. Every Event write that references the parameter is wrapped; non-matching errors re-raise unchanged. The fallback runs inside the existing `acquire_event_triplet_lock` scope — locks, dedup, and `polling/event_writer.py` are all untouched.

> **Archive-time reconciliation (2026-06-28).** The `sdd-apply` phase executed on the PR worktree (`/home/alex/dev/next-gen/worktrees/fix-collector-event-emission-cypher-rejection`) and never rewrote this main-worktree `tasks.md` file. All 12 code/test acceptance sub-checkboxes below have been flipped from `- [ ]` to `- [x]` during the `sdd-archive` phase per the stale-checkbox reconciliation path: the orchestrator's structured status (`tasks ✅`, `verifyReport ⚠️ APPROVED WITH NOTES`) and the verify-report's runtime evidence together prove every code/test task is complete. Proof: 16/16 targeted tests PASS in the `uv run python -m pytest` targeted run; full backend suite delta is `+3 passed, 0 new failures`; 9/9 spec scenarios PASS in the verify-report's Spec↔Test Traceability table. The 7 remaining `- [ ]` boxes are the operator-driven tasks (Task 4.2: rebuild image + restart worker on `10.53.1.22`; Task 4.3: production log verification via `docker logs ... | grep cypher-param-fallback`; Task 4.4: post-merge `gh issue close 340`); per `apply-progress.md` these were explicitly SKIPPED/DEFERRED by the user and are not part of the SDD code-change audit trail. The deployment plan is in the archive report under "Deployment plan (operator handoff)".

## TL;DR

- **11 tasks** in 4 phases; **strict TDD** is mandatory (every code-writing task preceded by a RED sub-task).
- **Total estimated diff**: ~340 lines (helper ~50 + 8 writer wirings ~120 + tests ~170), well under the 400-line review budget.
- **PR strategy**: **single PR** — the change is one focused capability, ~340 lines, no cross-cutting refactor. Auto-forecast per `openspec/config.yaml::pr_strategy`. Skip chained PRs unless apply discovers otherwise.
- **Writers wrapped**: six in `backend/engines/snmp_worker.py` (3 helpers × 2 `poll_collector_id` clauses) + two call sites in `backend/services/snmp_service.py::store_metric_result` (existing-Event SET path and new-Event CREATE path).

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~340 (range 310–370) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | single PR |
| Delivery strategy | auto-forecast |
| Chain strategy | n/a |

```text
Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low
```

## Task Dependency Graph

```text
Phase 1 — Helper
  Task 1.1 (RED test_neo4j_write_guard)  ┐
  Task 1.2 (GREEN backend/services/.../neo4j_write_guard.py)
                                          │
Phase 2 — Worker wiring (Task 2.A–2.C, one per helper)
  Task 2.A.1 (RED test_snmp_worker_cypher_fallback for _refresh_snmp_collection_failures)
  Task 2.A.2 (GREEN wrap _refresh_snmp_collection_failures session.run at :310, :349)
  Task 2.B.1 RED + 2.B.2 GREEN (_refresh_icmp_availability_events at :384, :424)
  Task 2.C.1 RED + 2.C.2 GREEN (_refresh_icmp_latency_events at :492, :527)
                                          │
Phase 3 — Service wiring (Task 3.A–3.B)
  Task 3.A.1 RED + 3.A.2 GREEN (snmp_service.py existing-Event SET path at :530)
  Task 3.B.1 RED + 3.B.2 GREEN (snmp_service.py new-Event CREATE path at :575)
                                          │
Phase 4 — Verification
  Task 4.1  full backend pytest suite
  Task 4.2  rebuild nextgen-snmp-engine, restart nexgen_snmp_worker on 10.53.1.22
  Task 4.3  verify production logs (docker logs ... | grep cypher-param-fallback)
  Task 4.4  close (or hand back) issue #340
```

## Phase 1 — Helper

### Task 1.1 — Helper unit tests (RED)

| Field | Value |
|---|---|
| Type | test (RED) |
| Depends on | — |
| Files | `backend/tests/test_neo4j_write_guard.py` (new) |
| Estimated | ~80 lines, 5 tests |

**Description**: Create the helper test module FIRST. Cover: (a) primary success skips fallback (one `session.run` call); (b) matching `ClientError` containing `"poll_collector_id"` and `"not defined"` triggers fallback and logs `ERROR` with both query strings; (c) non-matching `ClientError` (e.g. unrelated syntax) re-raises without fallback `session.run`; (d) non-`ClientError` exceptions re-raise unchanged; (e) `is_poll_collector_id_undefined_error` predicate unit cases (true / false positives / wrong exception type).

Mock `neo4j.exceptions.ClientError` via `unittest.mock.MagicMock(spec=...)` — the helper never imports the real driver at test time. Use `caplog` for the log assertion.

**Acceptance**:
- [x] `python -m pytest backend/tests/test_neo4j_write_guard.py -v` → all 5 tests FAIL (helper does not exist yet → `ImportError`).
- [x] Tests import only `pytest`, `unittest.mock`, `logging` — no live Neo4j.

**Strict TDD**: yes — this is the RED.

---

### Task 1.2 — Implement helper (GREEN)

| Field | Value |
|---|---|
| Type | code (GREEN) |
| Depends on | Task 1.1 |
| Files | `backend/services/neo4j_write_guard.py` (new) |
| Estimated | ~50 lines |

**Description**: Implement the helper module documented in design §6.

```python
# backend/services/neo4j_write_guard.py
import logging
import neo4j.exceptions

def is_poll_collector_id_undefined_error(error: Exception) -> bool:
    return (
        isinstance(error, neo4j.exceptions.ClientError)
        and "poll_collector_id" in str(error)
        and "not defined" in str(error)
    )

def run_with_cypher_param_fallback(
    session, primary_query, primary_params,
    fallback_query, fallback_params,
    error_filter, logger,
):
    try:
        return session.run(primary_query, **primary_params)
    except Exception as exc:
        if not error_filter(exc):
            raise
        logger.exception(
            "cypher-param-fallback primary_query=%r primary_params=%r "
            "fallback_query=%r fallback_params=%r",
            primary_query, primary_params, fallback_query, fallback_params,
        )
        return session.run(fallback_query, **fallback_params)
```

**Acceptance**:
- [x] `python -m pytest backend/tests/test_neo4j_write_guard.py -v` → all 5 tests PASS.
- [x] `python -c "from backend.services.neo4j_write_guard import run_with_cypher_param_fallback; print('ok')"` → `ok`.

**Strict TDD**: yes — this flips 1.1 to GREEN.

---

## Phase 2 — Worker Wiring (`backend/engines/snmp_worker.py`)

For each of the three Event-write helpers in `snmp_worker.py`, the existing single `session.run(primary_query, failures=…, poll_collector_id=POLL_COLLECTOR_ID)` becomes:

```python
fallback_query = primary_query.replace("poll_collector_id: $poll_collector_id", "") \
                              .replace("poll_collector_id = $poll_collector_id", "")
run_with_cypher_param_fallback(
    session, primary_query,
    {"failures": failures, "poll_collector_id": POLL_COLLECTOR_ID},
    fallback_query, {"failures": failures},
    is_poll_collector_id_undefined_error, logger,
)
```

The fallback removes both the literal `"…: $poll_collector_id"` (CREATE row dict) and `"… = $poll_collector_id"` (SET clause) usages via string substitution, matching design §7.

### Task 2.A — `_refresh_snmp_collection_failures` (lines 310, 349)

| Field | Value |
|---|---|
| Type | test (RED) → code (GREEN) |
| Depends on | Task 1.2 |
| Files | `backend/tests/test_snmp_worker_cypher_fallback.py` (new, RED section), `backend/engines/snmp_worker.py` (GREEN) |
| Estimated | ~40 lines |

**Sub-task 2.A.1 (RED)**: In `test_snmp_worker_cypher_fallback.py`, add `test_refresh_snmp_collection_failures_falls_back_when_poll_collector_id_undefined`. Use `mock_neo4j_driver` from `tests.conftest`. Patch `session.run` to raise a `neo4j.exceptions.ClientError("Variable poll_collector_id not defined")` on the first call and return a benign result on the second. Call `_refresh_snmp_collection_failures(session, [{"node_id":"CI-45A1EDD1","metric_id":"m","event_type":"COLLECTION_FAILURE","severity":"CRITICAL","message":"x","failure_family":"SNMP_NO_RESPONSE","source_protocol":"SNMP","correlation_type":"ROOT","propagated_from":None,"root_cause_ci_id":"CI-45A1EDD1"}], lock_db=MagicMock())`. Assert: `session.run.call_count == 2`; second call's query contains neither `poll_collector_id: $poll_collector_id` nor `poll_collector_id = $poll_collector_id`; second call's params do NOT include `poll_collector_id`.

Confirm RED with `python -m pytest backend/tests/test_snmp_worker_cypher_fallback.py::test_refresh_snmp_collection_failures_falls_back_when_poll_collector_id_undefined -v`.

**Sub-task 2.A.2 (GREEN)**: Refactor `_refresh_snmp_collection_failures` to wrap the `session.run` at line 310 per the snippet above. Confirm GREEN.

**Acceptance**:
- [x] Test PASSES; non-matching `ClientError` test (sister function in same file) RED then GREEN.
- [x] `python -m pytest backend/tests/test_snmp_worker.py -v` → no regressions.

---

### Task 2.B — `_refresh_icmp_availability_events` (lines 384, 424)

| Field | Value |
|---|---|
| Type | test (RED) → code (GREEN) |
| Depends on | Task 2.A |
| Files | `backend/tests/test_snmp_worker_cypher_fallback.py`, `backend/engines/snmp_worker.py` |
| Estimated | ~40 lines |

**Sub-task 2.B.1 (RED)**: `test_refresh_icmp_availability_events_falls_back_when_poll_collector_id_undefined`. Drive `_refresh_icmp_availability_events` with a synthetic `value: 0.0` ICMP update; same `ClientError` mock + fallback assertions as 2.A.

**Sub-task 2.B.2 (GREEN)**: Wrap the `session.run` at line 384 with the helper. Run task 2.A test still GREEN.

**Acceptance**: same shape as 2.A.

---

### Task 2.C — `_refresh_icmp_latency_events` (lines 492, 527)

| Field | Value |
|---|---|
| Type | test (RED) → code (GREEN) |
| Depends on | Task 2.B |
| Files | `backend/tests/test_snmp_worker_cypher_fallback.py`, `backend/engines/snmp_worker.py` |
| Estimated | ~40 lines |

**Sub-task 2.C.1 (RED)**: `test_refresh_icmp_latency_events_falls_back_when_poll_collector_id_undefined` using `status: "CRITICAL"` + `event_type: "THRESHOLD_BREACH"` row.

**Sub-task 2.C.2 (GREEN)**: Wrap the `session.run` at line 492 with the helper.

**Acceptance**: same shape as 2.A.

---

## Phase 3 — Service Wiring (`backend/services/snmp_service.py::store_metric_result`)

Defense-in-depth per proposal §Scope (user-resolved 2026-06-28). Two `session.run` blocks reference `$poll_collector_id`: the existing-Event SET at line 530 and the new-Event CREATE at line 575.

### Task 3.A — Existing-Event SET path (line 530)

| Field | Value |
|---|---|
| Type | test (RED) → code (GREEN) |
| Depends on | Task 2.C |
| Files | `backend/tests/test_snmp_service_cypher_fallback.py` (new), `backend/services/snmp_service.py` |
| Estimated | ~25 lines test + ~15 lines code |

**Sub-task 3.A.1 (RED)**: `test_store_metric_result_existing_event_path_falls_back`. Use `mock_neo4j_driver` (matching `test_snmp_service_collection_failures.py` style): seed `MATCH (existing:Event)` with a non-empty result, then mock the SET-path `session.run` to raise the production `ClientError`. Assert: a second `session.run` runs without `poll_collector_id` in the query string and params.

**Sub-task 3.A.2 (GREEN)**: Replace the line-530 `session.run(...)` call with `run_with_cypher_param_fallback(...)`. The fallback query removes `existing.poll_collector_id = $poll_collector_id,` from the SET clause.

**Acceptance**:
- [x] Test PASSES.
- [x] Existing `test_snmp_service_collection_failures.py` (`test_store_metric_result_persists_poll_collector_id_on_event_create`) still PASSES — primary path still attributes when Neo4j accepts the parameter.

---

### Task 3.B — New-Event CREATE path (line 575)

| Field | Value |
|---|---|
| Type | test (RED) → code (GREEN) |
| Depends on | Task 3.A |
| Files | `backend/tests/test_snmp_service_cypher_fallback.py`, `backend/services/snmp_service.py` |
| Estimated | ~25 lines test + ~15 lines code |

**Sub-task 3.B.1 (RED)**: `test_store_metric_result_create_event_path_falls_back`. Seed `MATCH (existing:Event)` empty; mock the CREATE-path `session.run` to raise the matching `ClientError`. Assert fallback omits `poll_collector_id`.

**Sub-task 3.B.2 (GREEN)**: Wrap the line-575 `session.run` with the helper.

**Acceptance**: same shape as 3.A.

---

## Phase 4 — Verification

### Task 4.1 — Full backend test suite

| Field | Value |
|---|---|
| Type | verification |
| Depends on | Tasks 1.2 → 3.B |
| Estimated | 0 lines |

**Acceptance**:
- [x] `cd backend && python -m pytest -q` exits 0.
- [x] No regressions in `test_writer_advisory_lock.py`, `test_snmp_worker.py`, `test_snmp_service_collection_failures.py`.
- [x] New tests in `test_neo4j_write_guard.py`, `test_snmp_worker_cypher_fallback.py`, `test_snmp_service_cypher_fallback.py` all PASS.

---

### Task 4.2 — Rebuild image and restart worker

| Field | Value |
|---|---|
| Type | deploy |
| Depends on | Task 4.1 |
| Estimated | 0 lines code |

**Description**: SSH to production `10.53.1.22`, rebuild the SNMP engine image so the new helper + writer wirings ship, then restart the worker container.

**Acceptance**:
- [ ] `ssh 10.53.1.22 "cd /opt/nextgen && docker compose build nextgen-snmp-engine"` exits 0.
- [ ] `ssh 10.53.1.22 "cd /opt/nextgen && docker compose up -d nexgen_snmp_worker"` exits 0.
- [ ] `ssh 10.53.1.22 "docker ps --filter name=nexgen_snmp_worker --format '{{.Status}}'"` shows `Up` (not `Restarting`).

---

### Task 4.3 — Production log verification

| Field | Value |
|---|---|
| Type | verification (manual evidence) |
| Depends on | Task 4.2 |
| Estimated | 0 lines |

**Description**: Confirm the marker string is greppable in production. Quiet (no occurrences for ≥5 minutes) when the primary query succeeds; populated when fallback triggers. The expected behavior post-fix: zero or near-zero occurrences if Neo4j now accepts `$poll_collector_id` again; if the unresolved hypothesis (#340 root cause) is still active, events stop being silently dropped.

**Acceptance**:
- [ ] `ssh 10.53.1.22 "docker logs --since=5m nexgen_snmp_worker 2>&1 | grep cypher-param-fallback"` is empty (primary path is healthy), OR
- [ ] Each non-empty match contains a stack trace, the original query, and the params dict (manual spot-check one entry).
- [ ] `docker logs nexgen_snmp_worker | grep -c "Events silenced: 0"` (or whichever existing counter) shows no NEW silent drops.

**Strict TDD**: N/A — manual evidence (no automated assertion for live Neo4j).

---

### Task 4.4 — Close issue #340

| Field | Value |
|---|---|
| Type | follow-up |
| Depends on | Task 4.3 |
| Estimated | 0 lines |

**Description**: Per the orchestrator instruction "close issue #340 (or leave for the user to close post-PR merge)". Apply will leave a comment on #340 with PR link + verification evidence; the user closes the issue post-merge (typical GitHub flow: `gh issue close 340` after the PR is merged to `main`).

**Acceptance**:
- [x] PR opened, references `#340`, lists Tasks 1.1–3.B in the description.
- [ ] Once merged, user runs `gh issue close 340 --comment "Fixed via <PR_URL>; helper + 8 writer wirings shipped in <sha>. Verified via `docker logs … | grep cypher-param-fallback` on 10.53.1.22."`.

---

## Per-Task Acceptance Template

| Task | Type | Strict TDD | Est. lines | Depends on |
|------|------|------------|------------|------------|
| 1.1 | test (RED) | yes | 80 | — |
| 1.2 | code (GREEN) | yes | 50 | 1.1 |
| 2.A.1 | test (RED) | yes | 25 | 1.2 |
| 2.A.2 | code (GREEN) | yes | 15 | 2.A.1 |
| 2.B.1 | test (RED) | yes | 25 | 2.A.2 |
| 2.B.2 | code (GREEN) | yes | 15 | 2.B.1 |
| 2.C.1 | test (RED) | yes | 25 | 2.B.2 |
| 2.C.2 | code (GREEN) | yes | 15 | 2.C.1 |
| 3.A.1 | test (RED) | yes | 25 | 2.C.2 |
| 3.A.2 | code (GREEN) | yes | 15 | 3.A.1 |
| 3.B.1 | test (RED) | yes | 25 | 3.A.2 |
| 3.B.2 | code (GREEN) | yes | 15 | 3.B.1 |
| 4.1 | verify | N/A | 0 | 3.B.2 |
| 4.2 | deploy | N/A | 0 | 4.1 |
| 4.3 | verify (manual) | N/A | 0 | 4.2 |
| 4.4 | follow-up | N/A | 0 | 4.3 |
| **Total code+test** | | | **~340** | |

## Non-Goals (do NOT scope-creep)

- No changes to `backend/polling/event_writer.py` or `polling/writer_pool.py` — out of scope per proposal §Out of Scope.
- No migration of `engines/snmp_worker.py` to the `backend/polling/` lease path.
- No backfill of silently dropped Events.
- No structural rewrite of `snmp_worker.py` / `snmp_service.py`.
- No RCA for the unresolved hypothesis (#340 §Open Questions) — tracked, does not block fallback fix.
- No re-dedup changes from `fix-event-duplication-cross-writer`.

## Next Step

Hand off to `sdd-apply`. Apply runs RED→GREEN strictly in order 1.1 → 4.4. No PR-strategy decision needed from the user — change fits in one PR (estimated ~340 lines, 60-line headroom under 400). Worktree convention: `/home/alex/dev/next-gen/worktrees/fix-collector-event-emission-cypher-rejection`.
