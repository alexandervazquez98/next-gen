# Verify Report: service-management-catalog PR 4 (WU 6 + WU 7)

## Status

**PASS** for PR 4 verification of Work Units 6 and 7.

PR 4 implementation matches REQ-06 and REQ-07 acceptance criteria with strict-TDD RED-first evidence in the test suite, atomic write semantics, lock-ordered full-batch behavior, and reference-sheet validation. Overall SDD change remains NOT archive-ready (PR 5 / WU 8 + WU 9 still unchecked).

## Structured status and actionContext findings

- Active change: `service-management-catalog`.
- Artifact store: `openspec` repo files.
- Workspace: `/Users/macbook/Library/CloudStorage/OneDrive-SharedLibraries-Onedrive/PROGRAMMING/next-gen/.worktrees/service-management-catalog-pr4`.
- Branch: `feat/service-management-catalog-pr4`.
- HEAD: `ce4197f9404891bbc7e422fef4d0e1a3c5fe03b0`.
- Runtime: Python 3.11.15 from `service-management-catalog-pr3/.venv/bin/python` (shared local venv).
- `strict_tdd: true` honored — RED-first evidence preserved in `test_itsm_imports_pr4.py`; GREEN/REFACTOR commits documented in `apply-progress.md` § "PR 4 — WU 6 + WU 7 atomic XLSX imports".
- Action constraints honored: no source edits to production code, no commit, no push. Only the verify-report artifact was added and committed.

## Spec-to-code trace (REQ-06 / REQ-07)

### REQ-06 — Catalog import atomicity and template contract

| Spec scenario | Implementation | Evidence |
|---|---|---|
| Required headers `service_id`, `name`, `SLA`, `description`, `service_type`, `value_stream` | `services/itsm_imports/catalog_import.py::CATALOG_REQUIRED_HEADERS` (line 32) used by `build_catalog_template_workbook` (line 50) and validated by `parse_catalog_workbook` via `collect_header_errors` | `TestCatalogTemplate::test_template_emits_required_sheets`; `TestCatalogHeaderValidation::test_missing_required_header_returns_structured_error` |
| `SLA` header accepted, `sla_target_minutes` rejected | `CATALOG_DISALLOWED_HEADERS = ("sla_target_minutes",)` (line 42); `collect_header_errors` emits `invalid_header` for the disallowed token | `TestCatalogHeaderValidation::test_sla_target_minutes_header_is_rejected` |
| Reference sheet `Ref - Value Streams` listing active dictionary values | `build_catalog_template_workbook` creates `CATALOG_REF_SHEET = "Ref - Value Streams"` from `value_stream_lookup.list_active()` | `TestCatalogTemplate::test_template_emits_required_sheets` |
| Workbook validation runs before any write | `import_catalog_workbook` → `parse_catalog_workbook` (raises `ImportValidationError`) → pydantic validation → only then `repository.bulk_create` | `TestCatalogAtomicity::test_invalid_workbook_persists_zero_rows`; live trace confirmed `bulk_create.called == False` on validation failure |
| Valid workbook persisted in one atomic commit | `repositories/itsm_service_catalog_repo.py::bulk_create` uses `session.execute_write(write_transaction)` — single Neo4j write transaction per `execute_write` semantics | `TestCatalogAtomicity::test_valid_workbook_persists_all_rows` (calls `bulk_create` with both rows; `imported_count == 2`) |
| Structured row/field error contract with cap | `errors.py::IMPORT_ERROR_CAP = 200`, `ImportValidationError.to_payload()` returns `{status, message, errors:[{row,field,code,reason}], error_count}` | `TestCatalogRowValidation::test_error_payload_caps_results` |
| File guard (`.xlsx` + size limit) | `workbook.py::guard_xlsx_payload` checks bytes, max size, openpyxl `load_workbook` validity | `TestCatalogFileGuard::test_non_xlsx_payload_rejected` |

### REQ-07 — Ticket import atomicity, reference sheets, compatibility, assignee

| Spec scenario | Implementation | Evidence |
|---|---|---|
| Template includes ticket sheet and reference sheet listing valid services filtered by `service_type` (incl. value-stream context) | `ticket_import.py::build_ticket_template_workbook` creates `TICKET_SHEET`, `TICKET_REF_INCIDENT`, `TICKET_REF_SERVICE_REQUEST`; rows include `service_id, name, value_stream`; filters by `service_type` and `active` | `TestTicketTemplate::test_template_includes_three_reference_sheets`; live trace produced `[['service_id','name','value_stream'], ['svc-inc-1','Net','operate']]` and `[['svc-req-1','Access','deliver']]`; inactive `svc-inc-2` correctly excluded |
| Reference sheet listing active users | `ticket_import.py` populates `TICKET_REF_USERS` from `user_repository.list_active()` when present; never breaks template generation if absent | Live trace produced `[['op1','Op One',True]]` |
| Validation runs before any ticket write | `import_ticket_workbook` → `parse_ticket_workbook` → pydantic model build → only then `acquire_user_locks_in_order` → only then `bulk_create_with_generated_ids` | `TestTicketAtomicityAndLocking::test_invalid_workbook_persists_zero_tickets`; live trace confirmed zero `bulk_create_with_generated_ids` calls on invalid input |
| Validates assignee (existence + active) | `_normalize_ticket_row` (line 164-169) calls `user_repository.get_by_username` and rejects inactive with `user_inactive` | `TestTicketRowValidation::test_inactive_user_reports_row_error` |
| Validates compatibility (`service_type` match + active + exists) | `_normalize_ticket_row` (line 151-162) checks `catalog_repository.get_by_id`, rejects not-found / inactive / type-mismatch | `TestTicketRowValidation::test_incompatible_service_type_reports_row_error` |
| Validates required fields | `_normalize_ticket_row` checks `title`, `description`, `service_catalog_id`, `assignee_username`, `type` enum | `TestTicketRowValidation::test_missing_assignee_reports_row_error` |
| Atomic persistence on success | `repositories/ticket_folio_repo.py::bulk_create_with_generated_ids` uses `session.execute_write(write_transaction)`; each iteration allocates sequence, creates ticket, merges `FOR_SERVICE` — all in one Neo4j write transaction | `TestTicketAtomicityAndLocking::test_valid_workbook_persists_all_tickets` (returns 2, called once with both payloads) |
| Generated numeric `ticket_id` per ticket | `_CREATE_TICKET_FOLIO_QUERY` allocates from `TicketSequence {name: 'ticket_folio'}` inside the same transaction; matches PR 1/PR 2 contract | Already covered by `test_ticket_folio_repo.py::test_create_with_generated_id_*` (green) |
| Exactly one active assignee per ticket | `assignee_username` is required on `TicketFolioCreate`; `parse_ticket_workbook` rejects missing or inactive | Domain contract enforced; row-level rejection confirmed |
| Lock-ordered full-batch acquisition | `import_ticket_workbook` computes `sorted({payload_model.assignee_username.lower() for payload_model in normalized})` then `acquire_user_locks_in_order`; helper returns deduped normalized order; lock acquired before any Neo4j write | `TestTicketAtomicityAndLocking::test_lock_acquisition_is_sorted_and_deduped`; live trace with out-of-order `op2`/`op1` confirmed captured `["op1","op2"]` |
| On lock acquisition failure, no partial writes | `acquire_user_locks_in_order` raises `RuntimeError("user_lock_timeout")` before `bulk_create_with_generated_ids` is called; import wrapper raises `ImportValidationError` so the router surfaces a 400; `bulk_create_with_generated_ids` is never reached | Live trace confirmed the order: `parse → pydantic → acquire_user_locks_in_order → bulk_create_with_generated_ids` |
| Lock held through the Neo4j write | `pg_session` is passed to `import_ticket_workbook`, the helper issues `pg_advisory_xact_lock` on the open session; the lock is `xact`-scoped so it remains held through any subsequent `session.execute_write` call; the router closes the session in `finally` | `services/user_lock.py` uses `pg_advisory_xact_lock`; router `import_ticket_workbook` handler wraps call in `try/except/finally` with `pg_session.close()` |

## Verification commands and exit codes

```text
cd backend && python -m pytest tests/test_itsm_imports_pr4.py -v
  → 16 passed in 1.24s   (exit 0)

cd backend && python -m pytest \
    tests/test_itsm_imports_pr4.py \
    tests/test_itsm_domain_contracts.py \
    tests/test_itsm_service_catalog_service.py \
    tests/test_ticket_folio_service.py \
    tests/test_ticket_folio_repo.py \
    tests/test_routers_itsm.py \
    tests/test_routers_users.py \
    tests/test_users.py \
    tests/test_migration_itsm_catalog.py \
    tests/test_itsm_startup_checks.py -q
  → 1 failed, 102 passed, 1 warning in 2.67s   (exit 1; pre-existing PR2 recovery finding, see below)

cd backend && python -m pytest -q --ignore=tests/test_writer_advisory_lock.py
  → 4 failed, 1733 passed, 1 skipped, 50 warnings in 26.21s   (exit 1; pre-existing failures only)

cd backend && python -m compileall -q services/itsm_imports
  → ok   (exit 0)
cd backend && python -m compileall -q routers tests/test_itsm_imports_pr4.py
  → ok   (exit 0)

git diff --check
  → exit 0
```

## Pre-existing failures (NOT caused by PR 4)

The four failures in the broader backend run all live in files NOT touched by PR 4 commits (`39f794e..HEAD`). `git log` on each file confirms they were authored by PR 1 / PR 2 / PR 3 / pre-chain commits.

| Failing test | Origin | Notes |
|---|---|---|
| `tests/test_itsm_service_catalog_service.py::TestServiceCatalogService::test_create_catalog_defaults_to_active_and_normalizes_aliases` | PR 2 boundary extension | Test passes `id` + `sla_minutes` aliases without the now-mandatory `description` / `value_stream`. PR 2 recovery repair explicitly documented this as a carried-over finding in `apply-progress.md` § "PR 4 verification evidence" and the task list still records it as known. |
| `tests/test_service_management_pr1.py::test_catalog_api_then_same_type_ticket_uses_persisted_type_and_active_status` | PR 1 / PR 2 boundary | Same apply-progress entry as above; calls `create_service_catalog(..., value_stream_lookup=...)` whose kwarg signature was later removed when the lookup seam moved into the import path. Pre-existing PR2-recovery failure. |
| `tests/test_auth_router_refresh.py::TestCookieDomainAndSecure::test_get_cookie_domain_and_secure_https_hostname` | Auth chain (pre-PR1) | Cookie domain / secure-flag behavior regression; unrelated to Service Management. |
| `tests/test_auth_router_refresh.py::TestCookieDomainAndSecure::test_get_cookie_domain_and_secure_cookie_domain_override` | Auth chain (pre-PR1) | Same root cause as above. |

`git log 39f794e..HEAD -- <file>` returns **empty** for every one of the four failing files, confirming PR 4 did not introduce them.

## Open risks (WARNING — require maintainer acknowledgment)

1. **Inherited unbounded `pg_advisory_xact_lock` timeout (PR 3).** WU 7 propagates `RuntimeError("user_lock_timeout")` from `acquire_user_locks_in_order` to the import path; if a deactivation holds a lock longer than the timeout, the import rolls back. The design called for a 5 s bounded default; this is not yet pinned in `services/user_lock.py`. Same caveat carried verbatim from the PR 3 verify report and the `apply-progress.md` lock-timeout note.
2. **PR 4 size:exception.** Total diff vs. cherry-pick base `39f794e` is `881 insertions / 4 deletions` across 11 files (production ~500 lines; tests ~377 lines). Slightly above the 800-line review budget; follows the same `size:exception` precedent set by PR 3 (1220 lines).
3. **No dedicated live-lock integration test.** `test_lock_acquisition_is_sorted_and_deduped` proves the order of usernames passed to the helper; the helper itself is unit-tested in `test_users.py`. There is no concurrent deactivation test that proves cross-process lock behavior — this matches the design plan and is scheduled for WU 9 (end-to-end release verification).
4. **`pg_session` is never explicitly committed on import success.** The advisory lock is released when the router closes the session in `finally` (auto-rollback ends the transaction and releases the xact lock). This is correct for advisory locks but means the PostgreSQL session writes no committed state. The router's `try/finally` guarantees closure on every code path, so the locks always release. Same pattern as the single-ticket `create_ticket_folio` service (`ticket_folio_service.py` lines 121-154).

## No-drift checks

- `tasks.md` lines 195 and 222: WU 6 and WU 7 headers read `## [x] Work Unit 6` / `## [x] Work Unit 7`. ✓
- `apply-progress.md` § "PR 4 — WU 6 + WU 7 atomic XLSX imports" contains RED/GREEN/TRIANGULATE/REFACTOR table; commit list `1d74062` (RED), `92971a1` (GREEN), `c979e96` (REFACTOR), `ce4197f` (docs). Internally consistent with `git log` on the branch.
- `apply-progress.md` claims 102 passed + 1 pre-existing failure; the live re-run on this verification matches (`102 passed, 1 failed`).

## Verdict

**PASS.** REQ-06 and REQ-07 are satisfied by the PR 4 implementation. Pre-existing failures are documented and confirmed not caused by PR 4. Lock semantics, atomicity, reference sheets, and structured error payloads all match the design contract. The two WARNINGs above are inherited risks from PR 3 and design-level choices already on file; they do not block shipping PR 4 and should be reviewed by the maintainer before archive.

Next recommended action: `apply-pr-creator` to open PR 4 against the tracker branch.