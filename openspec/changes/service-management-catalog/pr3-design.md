# PR 3 Slice — Cross-store assignee locking + user lifecycle

Status: Pre-implementation (planning complete, implementation deferred to a dedicated session).
Change ID: `service-management-catalog` — slice 3 of 5.
Owner: TBD.

## Purpose

This document scopes PR 3 of the `#401` chain. It does **not** re-derive the full design; it points at the artifacts that already cover the chain and lists only what PR 3 specifically owns.

If anything here contradicts `design.md` or `tasks.md`, the older artifacts win and this document is wrong. Update this file rather than letting it drift.

## PR 3 boundary (in scope)

PR 3 ships **Work Unit 3** from `tasks.md`:

> Work Unit 3 — backend: shared active-user locking + logical deactivation contract

Concretely, this means:

- Add the `assignee_username` field to `TicketFolioCreate` and `TicketFolioResponse`.
- Enforce single active assignee on ticket create (cardinality = 1).
- Reject inactive assignees at write-time under a held lock.
- Acquire a PostgreSQL per-user advisory lock for the duration of a ticket create; release on commit, rollback, or timeout.
- Add a logical `deactivate` operation on the user domain. No destructive delete. Historical ticket rows keep the snapshot assignee and display fields.
- Lock-ordered interleavings: ticket create/import vs. user deactivate serialize on the same per-user lock, with bounded timeout and deterministic retryable error.

## PR 3 boundary (out of scope — moved to later PRs)

These belong to PR 4 or PR 5 and **must not** be touched in PR 3:

- Bulk XLSX ticket import (`WU 6`, `WU 7`) — even though it consumes the same per-user lock, the import path itself is PR 4.
- Frontend assignee selector UX, ticket form rename, import wizard — PR 5 (`WU 8`).
- End-to-end release verification (`WU 9`).
- Catalog-side changes — already locked in by PR 2 (`WU 4`, `WU 5`).

## Source of truth (do not duplicate here)

These artifacts already define the PR 3 contract. Read them before opening a single file:

| Topic | File | Notes |
|---|---|---|
| Full technical design | `openspec/changes/service-management-catalog/design.md` | Lines 15, 24–36, 52–54, 80–82, 126–183 cover PR 3's slice end-to-end. |
| Acceptance requirements | `openspec/changes/service-management-catalog/specs/service-management-catalog/spec.md` | `REQ-04` (lines 87–101) and `REQ-05` (lines 103–111). |
| TDD work-unit definition | `openspec/changes/service-management-catalog/tasks.md` | `## Work Unit 3 — backend: shared active-user locking + logical deactivation contract` |
| Change-level proposal | `openspec/changes/service-management-catalog/proposal.md` | Scope decisions: clean-slate, no migration, exactly one active assignee, logical deactivation preserves history. |

## Code anchors PR 3 will touch

From the current `feat/service-management-catalog` HEAD (post-PR2):

| File | What changes |
|---|---|
| `backend/models/itsm.py` | Add `assignee_username: str` (required) to `TicketFolioCreate`. Add `_validate_assignee` field validator. Extend `TicketFolioResponse` with `assignee_username`, `assignee_display_name`, `assignee_currently_active`. |
| `backend/services/ticket_folio_service.py` | In `create_ticket_folio`: acquire per-user PG advisory lock keyed on `assignee_username`; resolve user via user repository; revalidate `is_active=True` while lock is held; keep lock through Neo4j write; release on commit/rollback. Surface deterministic errors: `assignee_inactive_at_write`, `assignee_not_found`, `user_lock_timeout`. |
| `backend/repositories/ticket_folio_repo.py` | Persist `assignee_username` on create; return it on read. Snapshot `assignee_display_name` at assignment time. |
| `backend/repositories/user_repo.py` | Add `get_by_username`, `deactivate(username, actor)` (logical, sets `is_active=False`, no row delete), and a hook for the same per-user PG lock. |
| `backend/routers/users.py` | Expose `POST /api/users/{username}/deactivate` (auth-gated). |
| `backend/tests/test_ticket_folio_service.py` | RED → GREEN tests for assignee cardinality, inactive rejection, lock-held revalidation, timeout behavior. |
| `backend/tests/test_routers_users.py` (or `test_users.py`) | RED → GREEN tests for deactivate endpoint and history-preservation contract. |
| `backend/tests/test_ticket_folio_repo.py` | RED → GREEN tests for assignee persistence and snapshot fields. |

## Decisions specific to PR 3 (recorded now to avoid drift)

These are decisions made at slice-planning time. They are not in the chain-level design; they are PR 3-only and may evolve during implementation if evidence contradicts them.

1. **Lock key derivation.** Use PostgreSQL `pg_advisory_xact_lock(hashtext('user:' || lower(username)))` so the lock is transaction-scoped and auto-released on commit/rollback. Reject `pg_advisory_lock` (session-scoped) to avoid leaks.
2. **Lock ordering on bulk paths.** When batch operations acquire multiple per-user locks in the same transaction, they must acquire in normalized (`lower()`) username order to prevent deadlock cycles. PR 3 implements the helper; PR 4 (import) consumes it.
3. **Snapshot fields on ticket.** `assignee_username`, `assignee_display_name`, and `assignee_active_at_assignment` are persisted at create time. `assignee_currently_active` is computed at read time by joining the user row. PR 3 stores the snapshot; PR 3 also stores `assignee_currently_active` as a denormalized convenience column updated by user-deactivation flows.
4. **Deactivation endpoint.** `POST /api/users/{username}/deactivate` (not `DELETE`) to make the logical nature explicit. Returns 204 on success; 404 if user not found; 409 if already inactive. Permission gate: requires `USER_MANAGE` permission.
5. **Deactivation does not touch ticket rows.** The implementation must verify (via RED test in `test_users.py`) that calling deactivate does not produce any write to `TicketFolio` nodes. Snapshot fields stay valid; `assignee_currently_active` is recomputed at read time.
6. **Strict TDD discipline.** Per `tasks.md` ground rule, every behavior change ships with failing RED tests first. The lock helper, the validator, and the deactivate endpoint each get their own RED → GREEN → TRIANGULATE → REFACTOR cycle in the same work unit.
7. **No frontend in this PR.** Even though PR 5 (`WU 8`) will surface the assignee selector, the backend field is required from PR 3 onward. Existing test payloads without `assignee_username` will fail validation; that's intentional and signals the contract change to any consumer still on the old shape.

## Verification gate (what must be true before PR 3 → PR 4)

This is the binary test set that proves PR 3 ships its contract. Run locally before opening the PR; CI re-runs the same on push.

```bash
# focused backend suite for PR 3
cd backend && python -m pytest \
  backend/tests/test_ticket_folio_service.py \
  backend/tests/test_ticket_folio_repo.py \
  backend/tests/test_itsm_domain_contracts.py \
  backend/tests/test_routers_itsm.py \
  backend/tests/test_routers_users.py \
  backend/tests/test_users.py \
  -q

# lint from backend/ (matches CI working-directory)
cd backend && python -m ruff check --config ruff.toml \
  models/itsm.py services/ticket_folio_service.py repositories/ticket_folio_repo.py \
  repositories/user_repo.py routers/users.py \
  tests/test_ticket_folio_service.py tests/test_ticket_folio_repo.py \
  tests/test_itsm_domain_contracts.py tests/test_routers_itsm.py \
  tests/test_routers_users.py tests/test_users.py
```

Acceptance before PR 3 is mergeable:

- All REQ-04 and REQ-05 scenarios pass with named RED tests.
- Existing PR1+PR2 tests (1700+ backend tests) still green.
- Lint clean from `backend/` CWD (the same perspective CI uses; do not rely on worktree-root ruff).
- No frontend changes in this PR.

## Open risks (carry into implementation)

- **Cross-store reconciliation.** A process crash between Neo4j commit and PostgreSQL commit leaves a ticket with a snapshot for a user that the user repo later deactivates. `design.md` line 182 names this as a reconciliation risk. PR 3 ships the invariant; reconciliation tooling is not in scope but should be flagged as follow-up.
- **Lock timeout policy.** The bounded timeout for `pg_advisory_xact_lock` is not pinned yet. PR 3 implementation must pick a default (suggested: 5s) and surface a `409 user_lock_timeout` on miss. If the team prefers a different default, update this file before coding.
- **Permission model for deactivate.** `USER_MANAGE` is the assumed permission kind; if the user module already uses a different name, align and document in the implementation commit message.

## Chain progress

| PR | Scope | Status |
|---|---|---|
| PR 1 | Backend ID/core contracts (`WU 1`, `WU 2`, PR1 boundary extension) | ✅ Merged (`#408`) |
| PR 2 | Catalog + value-stream domain (`WU 4`, `WU 5`) | ✅ Merged (`#412`) |
| **PR 3** | **Cross-store assignee locking + user lifecycle (`WU 3`)** | **🟡 Planning complete, implementation pending** |
| PR 4 | Atomic XLSX imports (`WU 6`, `WU 7`) | ⏳ Blocked on PR 3 |
| PR 5 | Frontend rename + compatibility + import UX (`WU 8`, `WU 9`) | ⏳ Blocked on PR 4 |

Tracker: `feat/service-management-catalog` (`#403`).
Implementation branch (when work starts): `feat/service-management-catalog-pr3` — already exists locally at `798eb66` post-tracker-fast-forward.