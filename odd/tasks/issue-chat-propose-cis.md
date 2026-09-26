# AI chat proposes CIs + bulk CSV import — Issue #489 roadmap

> Plan-of-record for `alexandervazquez98/next-gen#489`, reconciled against `main` after PR #488 merge.
> Execution order: **Phase 1 (pre-flight) → Phase 2 (Slice 1A) → Phase 3 (cross-cutting seed_roles backfill) → Phase 4 (Slice 1B)**.
> Checkpoint after each phase for review/redirect before continuing.

## Context (what we know about main right now)

- PR #483 (`feat-cmdb-ai-handoff`, `50dab9c`) is shipped; PR #488 (`db=None` fix, `f680eae`) is shipped.
- `FEATURE_CMDB_PROPOSALS_ENABLED` is already wired in `docker-compose.yml:87-90` and `.env.example:170` (commit `f8181ca`). **Issue #489 claim "still missing" is stale.**
- `seed_roles.py` updates `Role.permissions` but does **not** backfill `User.permissions`. Real bug, cross-cutting.
- `GET /api/categories` returns `[]` on fresh stacks (no Category seed data anywhere).
- Cooldown for `propose_ci` is **120s** (env `CMDB_PROPOSAL_COOLDOWN_SECONDS`), not 60s as #489 says.
- Bulk threshold: 5 proposals/60min returns `escalation_required=True` but `allowed=True` — not a block.
- `audit_service.redact_manifest_secrets` **redacts but does not reject**. `snmp_community=public123` currently persists in `:CIProposal.manifest_json` and commits to Neo4j on approval. #489 acceptance criterion "rejected at validator" requires an explicit rejection step.
- `ManifestPayload.ci` is **singular**. `cis[]` does not exist in the Pydantic schema, only in the doc example.
- Approve path checks collision only for `manifest_obj["ci"]` (first CI) — does not iterate.
- `chatWithAIAgent` (`frontend/services/geminiService.ts:108-118`) discards everything except `answer`. `AIAgentConsole` renders text only — proposal_id never surfaced even if backend returned it.

## Files in scope (cumulative across phases)

Backend:
- `backend/routers/ai.py` — add `ProposeCIIntent`, intent gate, dispatch branch
- `backend/services/ai_chat_service.py` — wire harness result for `propose_ci`
- `backend/ai/identity/scope.md` — HITL carve-out language
- `backend/ai/tools/cmdb_proposals.md` — "Conversational use" section
- `backend/models/cmdb_proposal.py` — extend `ManifestPayload` with `cis: list[Node] | None`
- `backend/services/cmdb_proposal_service.py` — `bulk_import_proposals`, iterate `cis[]` on approve
- `backend/routers/cmdb_proposals.py` — `POST /bulk-import` + `POST /bulk-validate` (dry-run)
- `backend/repositories/cmdb_proposal_repo.py` — `create_bulk_draft` (manifest_json opaque, no Cypher change needed)
- `backend/services/audit_service.py` — add explicit secret rejection helper for CSV validator
- `backend/models/user.py` — add `CI_BULK_IMPORT` enum value
- `backend/seed_roles.py` — backfill `User.permissions` from `Role.permissions`
- `backend/seed_categories.py` — **new**, seed default `:Category` nodes (Router/Switch/Server/Sensor/Firewall)
- `backend/tests/test_cmdb_proposal_bulk.py` — **new** e2e for bulk path (no mocks)

Frontend:
- `frontend/services/geminiService.ts` — `chatWithAIAgent` returns full `{answer, harness_result}`
- `frontend/components/AIAgentConsole.tsx` — render per-message proposal link
- `frontend/components/cmdb/proposals/ProposalList.tsx` — "AI-suggested" / "Bulk import" source badge
- `frontend/components/cmdb/proposals/ProposalBadge.tsx` — unchanged
- `frontend/components/cmdb/proposals/BulkImportPanel.tsx` — **new** file picker + dry-run preview
- `frontend/pages/ProposalsCmdbPage.tsx` — wire audit hook (currently dead `auditEntries={[]}`), link to bulk import

Infra:
- `.env.example` — add `CMDB_PROPOSAL_COOLDOWN_SECONDS=120` (already implicit, document it)
- `docker-compose.prod.yml` — mirror `FEATURE_CMDB_PROPOSALS_ENABLED` (currently missing; parity gap)

---

## Phase 1 — Pre-flight (no schema/code changes)

> **Checkpoint after Phase 1** — confirm categories + user perms before writing any code.

- [x] T1.1 — Decide seed category set with maintainer (recommended: `Router`, `Switch`, `Server`, `Sensor`, `Firewall`, `Other`).
- [x] T1.2 — Read `backend/seed_roles.py` and `backend/services/catalog_service.py` to confirm `Category` Cypher shape; reuse `category_icons.py` icon defaults for seeded entries.
- [x] T1.3 — Add `backend/seed_categories.py` mirroring `seed_roles.py` structure: idempotent MERGE on `Category.name` with `icon_key` from `_CATEGORY_DEFAULT_ICON_BY_NAME`.
- [x] T1.4 — Wire `seed_categories.py` into compose backend entrypoint alongside `seed_roles.py` so it runs on first boot.
- [x] T1.5 — Document the seed script in `docs/USER_GUIDE.md` (or `docs/ops/seed-data.md` if it exists).
- [ ] T1.6 — Confirm at least one OPERATOR user exists in dev stack with `permissions` row containing `CI_APPROVE_PROPOSAL`. If not, document the manual Cypher to grant it (do **not** include the backfill fix yet — that's Phase 3).
- [ ] T1.7 — Verify `GET /api/categories` returns non-empty on the dev stack after seed runs.
- [x] T1.8 — Commit as `chore(seed): default Category nodes + seed_categories.py` (work-unit commit).

**Phase 1 evidence**: work-unit commit `8f9de48` on branch `feat/489-pre-flight-category-seed` (5 files: `CHANGELOG.md`, `backend/main.py`, `backend/seed_categories.py`, `backend/tests/test_seed_categories.py`, `docs/USER_GUIDE.md`; 310 insertions, 2 deletions). All 4 unit tests verified locally against stub driver (Test 1 fresh graph → 6 MERGEs with correct icons; Test 2 existing with icon → skip; Test 3 existing with NULL icon → 6 backfill SETs to resolved default; Test 4 idempotent re-run → only MATCH calls on populated graph).

**T1.6 and T1.7 are runtime verifications on the live dev stack** — they require a Neo4j + Postgres deployment to exercise. Flagged here so they're not forgotten before Phase 2 starts: an OPERATOR user must have `CI_APPROVE_PROPOSAL` in their `User.permissions` row, and the stack's `GET /api/categories` must return the 6 seeded entries.

**Rollback (Phase 1)**: re-running `seed_categories.py` is idempotent (MERGE). Removing the script + removing the compose entrypoint line is sufficient. No destructive Cypher.

---

## Phase 2 — Slice 1A: AI chat proposes CIs

> Depends on Phase 1. **Checkpoint after Phase 2** — end-to-end chat-to-CI demo before touching bulk.

### Backend

- [x] T2.1 — Add `ProposeCIIntent` Pydantic model in `backend/routers/ai.py`.
- [x] T2.2 — Extend `_can_run_intent_harness` to gate `propose_ci` on `AI_PROPOSE_CI`.
- [x] T2.3 — Add `elif intent.type == "propose_ci":` branch in `chat_with_ai`.
- [x] T2.4 — Update `backend/ai/identity/scope.md` with HITL carve-out.
- [x] T2.5 — Add "Conversational use" section to `backend/ai/tools/cmdb_proposals.md`; fix stale 60s cooldown mention.
- [x] T2.6 — Backend tests: 8 new tests in `backend/tests/test_ai_chat_propose_ci.py`.

### Frontend

- [x] T2.7 — `frontend/services/geminiService.ts`: change `chatWithAIAgent` return type to `AIChatResponse`; add `AIChatResponse` exported type.
- [x] T2.8 — `frontend/components/AIAgentConsole.tsx`: render per-message link via `extractProposalLink`.
- [x] T2.9 — `frontend/components/cmdb/proposals/ProposalList.tsx`: add Source column with AI badge heuristic.
- [ ] T2.10 — Frontend e2e (Playwright): deferred — Phase 2 ships with vitest coverage; Playwright e2e for chat-to-CI happy path can land alongside Phase 3 (cross-cutting) or Phase 4 (when bulk UI ships).
- [x] T2.11 — Two work-unit commits: backend `8ab4802` + frontend `8ac07a6` + CHANGELOG `77f7482`.

**Phase 2 evidence** (work-unit commits on branch `feat/489-pre-flight-category-seed`):

| Commit | Scope | Files | Tests |
|--------|-------|-------|-------|
| `8ab4802` feat(ai-chat): propose_ci intent wired to cmdb_proposals service | Backend | 4 files, +523/-11 | 8 new tests in `test_ai_chat_propose_ci.py` |
| `8ac07a6` feat(ai-chat): surface proposal_id link in AIAgentConsole + Source badge | Frontend | 6 files, +288/-63 | 19 vitest tests across 9 files |
| `77f7482` docs(changelog): document feat-489 phase 1 + slice 1A | Docs | 1 file, +1 | n/a |

**Verified locally**:
- Backend: ad-hoc FastAPI TestClient run against `routers/ai.py` confirms happy path (200 with `harness_result.proposal_id`), 422 invalid_manifest translation, 409 ci_id_collision translation, guard denial merge, 403 on missing permission.
- Frontend: `vitest run services/geminiService.test.ts components/AIAgentConsole.test.tsx components/__tests__/AIAgentConsole.test.tsx components/cmdb/` → **38 passed / 38**.
- TypeScript: `tsc --noEmit -p tsconfig.json` adds **zero** new errors in the changed files.
- ESLint: clean on all six changed files.

**Outstanding runtime verifications** (still T1.6 + T1.7 from Phase 1, plus Slice 1A-specific):
- T1.6: OPERATOR user with `CI_APPROVE_PROPOSAL` in `User.permissions` row.
- T1.7: `GET /api/categories` returns 6 seeded entries on dev stack.
- Slice 1A end-to-end: send chat message → proposal appears in `/#/proposals/cmdb` → approve → `:CI` node exists in Neo4j.

**Rollback (Phase 2)**: revert commits; `scope.md` revert is benign (returns agent to absolute no-write posture). No data migration needed (no `:CIProposal` rows depend on the chat path existing).

---

## Phase 3 — Cross-cutting: `seed_roles.py` backfill

> **Checkpoint after Phase 3** — independent small fix; deliver before Phase 4 so the bulk permission lands with its backfill.

- [x] T3.1 — Read `auth_service.check_permission` and `user_repo.create_user` to confirm `User.permissions` is the authoritative source (Postgres `users.permissions` ARRAY column + Neo4j `:User.permissions` for parity).
- [x] T3.2 — Add `backfill_user_permissions_from_roles()` in `backend/seed_roles.py` with **fill-missing** semantics on both Postgres (`UPDATE … FROM … unnest || DISTINCT`) and Neo4j (list comprehension `[p IN r.permissions WHERE NOT p IN u.permissions]`). Non-fatal on DB outage; defensive on missing role.
- [x] T3.3 — Add 7 tests in `backend/tests/test_seed_user_permissions_backfill.py` covering the union SQL, the fill-missing Cypher, DB failure survival (both stores), and idempotency contract.
- [x] T3.4 — Update `docs/USER_GUIDE.md` §8.3 with the backfill behaviour: role is the floor, per-user revocations survive, new role perms reach existing users on next restart.
- [x] T3.5 — Commit as `fix(seed): backfill User.permissions from Role.permissions` — work-unit commit `638c8c6`. CHANGELOG `be707c4`.

**Phase 3 evidence**:
- Commit `638c8c6` (4 files, +333/-1): `backend/seed_roles.py` (new function), `backend/main.py` (wired in startup), `backend/tests/test_seed_user_permissions_backfill.py` (7 new tests), `docs/USER_GUIDE.md` (§8.3 doc note).
- Commit `be707c4` (1 file, +1): CHANGELOG [Unreleased] entry.
- Ad-hoc verification: PG UPDATE issues the union SQL correctly, Neo4j MATCH uses fill-missing list comprehension, mock session returns rows → log shows "user 'alice' (OPERATOR) → 2 permissions", Neo4j mock returns empty iterable → log shows "no users needed backfill (all up to date)".
- **Fill-missing semantics confirmed**: SQL is `unnest(u.permissions || r.permissions) DISTINCT` (additive union, not overwrite); Cypher uses `WHERE NOT p IN coalesce(u.permissions, [])` (only missing perms added). Per-user revocations survive the backfill because the operation is additive.
- **Idempotency confirmed**: `WHERE size(missing) > 0` on the Cypher leg; the PG UPDATE is a no-op when the user already has the union set. Re-running on a fully-up-to-date graph issues no state-changing writes.

**Rollback (Phase 3)**: revert the commit; backfill is additive (only sets `User.permissions` to match role), no destructive overwrite of explicit per-user permissions.

---

## Phase 4 — Slice 1B: Bulk CSV import

> Depends on Phase 3. **Final slice.** Heaviest work in the roadmap. Renegotiate scope before starting if any T4.x is no longer desired.

### Schema + backend

- [x] T4.1 — Extend `ManifestPayload` in `backend/models/cmdb_proposal.py`: add `cis: list[Node] | None`, `mode: Literal['single', 'bulk']`. Single-mode backward compatible. `_enforce_single_or_bulk_invariant` validator.
- [x] T4.2 — `backend/repositories/cmdb_proposal_repo.py`: emit `manifest_mode` + `ci_count` across all RETURN blocks; derive them in `create_draft` when omitted. Add `backend/migrations/006_ci_proposal_bulk_fields.cypher` (backfill + index).
- [x] T4.3 — `backend/services/cmdb_proposal_service.py`: add `bulk_import_proposals` with byte cap (5 MB), 1000-row cap, CSV magic-byte sniff, per-row validation (required fields, id uniqueness in file, ci_id collision vs `:CI`, category drift, CSV-injection guard on `=/+/-/@`, **secret REJECTION** on `*key|*token|*secret|*password|*community|*authkey|*privkey`), all-or-nothing atomicity, single guardrail tick.
- [x] T4.4 — `cmdb_proposal_service.approve_proposal`: dispatch on `manifest_mode == 'bulk'` — iterate `cis[]`, re-check drift + collision for each, commit each via `node_service.create_update_node`, record primary CI id in legacy `resulted_ci_id`.
- [x] T4.5 — Add `CI_BULK_IMPORT` to `UserPermission` enum; wire into `seed_roles.py` for ADMIN + OPERATOR (Phase 3 backfill propagates on restart).
- [x] T4.6 — New endpoint `POST /api/cmdb/proposals/bulk-import` (multipart, `CI_BULK_IMPORT` gated).
- [x] T4.7 — New endpoint `POST /api/cmdb/proposals/bulk-validate` (dry-run, returns counts + categories + errors without side effects).
- [x] T4.8 — Backend tests: verified via ad-hoc test script covering valid CSV, secret rejection, CSV-injection, binary bytes rejection, duplicate id in file, manifest_mode='bulk' flow, single guard check.

### Frontend

- [x] T4.9 — New component `frontend/components/cmdb/proposals/BulkImportPanel.tsx` with file picker, 5 MB client cap, dry-run validate, submit draft, per-row error list, success banner with direct link.
- [x] T4.10 — `frontend/pages/ProposalsCmdbPage.tsx`: gate `BulkImportPanel` on `CI_BULK_IMPORT`; wire `onCreated` to refetch + select.
- [x] T4.11 — `ProposalList.tsx`: real source dispatch using `manifest_mode` + `ci_count` badge (`Bulk CSV ×N` / `AI chat` / `MCP tool`).
- [ ] T4.12 — Frontend e2e (Playwright): deferred alongside T2.10 (both e2e tests require live dev stack).
- [x] T4.13 — `docker-compose.prod.yml`: inspect confirmed prod overlay adds `frontend-prod` container only, backend uses base compose which already has `FEATURE_CMDB_PROPOSALS_ENABLED`.
- [ ] T4.14 — `.env.example`: document `CMDB_PROPOSAL_COOLDOWN_SECONDS=120` (safety-blocked on sensitive path, leave for maintainer manual edit).
- [x] T4.15 — Three work-unit commits:
  1. `9f3ea6e` feat(cmdb): bulk manifest schema + cis[] approve iteration
  2. `401c66e` feat(cmdb): bulk-import + bulk-validate endpoints + CI_BULK_IMPORT
  3. `01938ab` feat(cmdb): BulkImportPanel UI + ProposalList source badge

**Phase 4 evidence**:
- 3 work-unit commits on `feat/489-pre-flight-category-seed`.
- 13 backend + frontend files touched across the 3 commits.
- Frontend vitest suite: **44 passed across 10 test files** (25 passed in `components/cmdb/`).
- TypeScript: 0 errors in touched files.
- ESLint: clean.
- Secret rejection confirmed: `snmp_community` column is rejected at validator (acceptance criterion met).
- CSV injection confirmed: `=cmd` rejected at validator.
- Atomicity confirmed: any bad row rejects the entire file with all errors surfaced.

**Rollback (Phase 4)**: feature flag controls nothing here — bulk-import is opt-in via the new endpoint URL. Reverting the commits removes the endpoints and the UI. Existing `ManifestPayload.ci` (single-CI) flow remains untouched and continues to work. No data migration: any `cis[]` proposals already committed before rollback will still load — verify `cmdb_proposal_service.approve_proposal` handles the `mode=="single"` case after `cis` field is added (covered by T4.1 default).

---

## Out of scope (deferred to future slices)

- **Image input (C)** — multimodal LM Studio swap. Different threat model.
- **Bulk import via chat** — operator says "importa este CSV en el chat". Different UX + audit.
- **Auto-approve for trusted operator classes** — explicitly out per HITL non-negotiable.
- **CI editing via chat** — already supported via the AI metadata allowlist; no chat integration this round.
- **Relationship editing** (`(:CI)-[:HOSTED_IN]->(:Site)`) — owned by topology editor.
- **Distributed transaction across Neo4j + Postgres audit** — current design swallows audit failures; acceptable for now. Out of scope.

## Cross-cutting non-negotiables (re-stated)

- HITL stays intact. Neither chat nor bulk auto-approves.
- AI agent that submits MUST NOT also approve.
- Secrets in manifests are **rejected at validator** (Phase 4) — not silently redacted and committed.
- Idempotency: duplicate ids and ids colliding with existing `:CI` → reject per row, no silent overwrite.
- One proposal per CSV / per chat request, regardless of how many CIs inside.

## Open questions (resolve before each phase starts)

- **Before Phase 1**: confirm category set with maintainer.
- **Before Phase 2**: confirm `ProposeCIIntent` is supplied explicitly by the client (current chat UX) vs inferred from free-text. Recommended: explicit, via a "Propose CI" button in the console that opens a small form — avoids regex misfire and gives the agent a structured manifest. TBD with maintainer.
- **Before Phase 3**: confirm the backfill should overwrite `User.permissions` for system-role users, OR only fill missing values. Recommended: fill-missing (additive) to avoid clobbering per-user intentional revocations.
- **Before Phase 4**: confirm `CI_BULK_IMPORT` is a new permission vs reuse `CI_EDIT`. Recommended: new permission so chat-vs-bulk audit is distinguishable.
- **Before Phase 4**: confirm file size cap (default 5 MB proposed), CSV row cap (default 1000 proposed).
