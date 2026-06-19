# Tasks: AI Chat Markdown Policies

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 500-750 total; Slice A ~330-480, Slice B ~170-270 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 / Slice A: runtime policies, templates, deterministic renderer, backend tests → PR 2 / Slice B: `docs/ai.md` developer manual and optional `backend/ai/README.md` link |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

## Implementation Checklist

### 0. Pre-apply delivery guard

- [x] Before implementation, confirm whether to proceed as chained PRs/slices or accept a size exception, because the total forecast exceeds the 400 changed-line review budget.
- [x] Do not deploy to `.22` or any other environment during this change unless the user explicitly approves deployment.

### Slice A: Runtime policies, templates, renderer, and tests

#### RED: policy/template artifact tests

- [x] Add failing tests in `backend/tests/test_ai_chat_service.py` or a focused backend test module that assert these files exist and contain required contract language:
  - `backend/ai/policies/response-boundaries.md`
  - `backend/ai/policies/lmstudio-runtime.md`
  - `backend/ai/policies/followup-intents.md`
  - `backend/ai/templates/event_list.md`
  - `backend/ai/templates/availability_check.md`
  - `backend/ai/templates/availability_check_batch.md`
- [x] Test that policy/template text covers: no invented harness execution, bounded `reachable`/`unreachable` ping semantics, unsupported RCA/congestion/power/cabling/firewall/service-health/stable/optimal/resolved/event-closure limits, follow-up trigger concepts, named-area matching, and the 5-CI batch cap.

#### GREEN: add markdown policies and templates

- [x] Create `backend/ai/policies/response-boundaries.md` with operational evidence boundaries, no direct model writes to Raven/SQLite/Neo4j/Postgres/CMDB, and unsupported-claim rules.
- [x] Create `backend/ai/policies/lmstudio-runtime.md` documenting `/v1/chat/completions`, backend-owned history, reasoning-model empty `content`, `LM_STUDIO_MAX_TOKENS`, `LM_STUDIO_TIMEOUT_SECONDS`, and context-length tradeoffs.
- [x] Create `backend/ai/policies/followup-intents.md` documenting event-list triggers, availability follow-up triggers, named-area fields, stopwords, and `availability_check_batch` cap.
- [x] Create `backend/ai/templates/event_list.md` with reviewed sections for count/filters, observed events, observed diagnosis, limitations, suggested next checks, and truncation notice.
- [x] Create `backend/ai/templates/availability_check.md` with CI/status/target/latency/detail, bounded-ping interpretation, and limitations.
- [x] Create `backend/ai/templates/availability_check_batch.md` with count, per-CI rows, bounded-ping interpretation, limitations, and cap wording.

#### RED: deterministic renderer and unsupported-claim tests

- [x] Add failing tests for `event_list` rendering that require harness facts, status/severity filters, CI names, messages, `last_seen` when present, truncation notice when `truncated=true`, and observed-symptom-only diagnosis.
- [x] Add failing tests for empty `event_list` rendering with status/severity qualifiers and no invented facts.
- [x] Add failing tests for `availability_check` rendering that require CI/ref, status, target, latency, detail, bounded-ping wording, and failure statuses such as `ci_not_found`, `invalid_target`, or `error` without claiming successful reachability.
- [x] Add failing tests for `availability_check_batch` rendering that require each checked CI up to the existing 5-CI cap, status/target/latency/detail, and bounded-ping wording.
- [x] Add failing unsupported-claim tests using representative event and ping-check samples. Assert unsafe affirmative phrases are absent while exact safe limitation phrases are present.

#### GREEN: loader and deterministic renderer

- [x] In `backend/services/ai_chat_service.py` or new `backend/services/ai_markdown.py`, add known-path bounded UTF-8 loading for `backend/ai/policies/` and `backend/ai/templates/`; use no user-controlled paths and safe `OSError` fallback.
- [x] Add `DETERMINISTIC_HARNESS_TYPES = {"event_list", "availability_check", "availability_check_batch"}` and a deterministic rendering entrypoint such as `render_harness_response(query, harness_result)`.
- [x] Implement `event_list` rendering from compact harness facts only; include filters/count/events/observed symptoms/limitations/next checks and avoid unsupported RCA or resolution claims.
- [x] Implement `availability_check` rendering from harness ping metadata only; distinguish `reachable`, `unreachable`, `ci_not_found`, `invalid_target`, and `error`.
- [x] Implement `availability_check_batch` rendering from existing batch result data only; preserve the current maximum of 5 CIs and bounded-ping semantics.
- [x] Reuse the existing Spanish preference helper where practical; do not add broad NLP or markdown DSL parsing.

#### RED/GREEN: LM Studio selection and regression preservation

- [x] Add failing tests that `complete_chat` bypasses `_post_lm_studio_chat_completion` for `event_list`, `availability_check`, and `availability_check_batch`, and returns a deterministic model label such as `deterministic-template` if response model reporting changes.
- [x] Add or preserve tests that no-harness chat still calls LM Studio and keeps the no-harness warning in the LM Studio payload.
- [x] Preserve or update existing tests for empty-content fallback so unknown/non-deterministic harness types still synthesize a safe fallback when LM Studio returns blank `content`.
- [x] Preserve regression coverage in `backend/tests/test_ai_chat_service.py` and related router tests for:
  - LM Studio `/v1/chat/completions` path and backend-managed history;
  - event status filters `OPEN`, `ACK`, `CLOSED`, `RECOVERED`, `ACTIVE`, `CONSOLE`;
  - event severity filters `CRITICAL`, `WARNING`, `INFO`;
  - `active_events`/unrecovered inference;
  - same-user history and latest event-list follow-up resolution;
  - named-area filtering such as `islas agrarias`;
  - `availability_check_batch` cap of 5 CIs;
  - permission gates before harness execution;
  - disabled LM Studio blocking harness side effects;
  - unsafe target rejection and bounded ping command behavior;
  - empty-content fallback safety.

#### TRIANGULATE and REFACTOR

- [x] Add at least one English and one Spanish deterministic rendering example in tests where feasible, without expanding scope into full localization.
- [x] Refactor duplicated fallback/renderer formatting in `backend/services/ai_chat_service.py` only after tests pass; keep rollback simple by isolating the deterministic branch.
- [x] Verify old LM Studio behavior remains available for non-harness chat and unknown harness types.

### Slice B: Developer manual and optional links

#### RED: manual coverage tests or manual evidence

- [ ] Add a lightweight doc test or checklist-style validation, if existing project conventions support it, that `docs/ai.md` exists and mentions required paths and boundaries. If no doc tests exist, record manual review evidence during verify.

#### GREEN: developer documentation

- [ ] Create `docs/ai.md` covering LM Studio connection/env vars, OpenAI-compatible `/v1/chat/completions`, model/timeout/max-token/context-length tuning, and reasoning-model empty-content behavior.
- [ ] Document identity files: `backend/ai/identity/Soul.md`, `backend/ai/identity/scope.md`, `backend/ai/identity/context-policy.md`, and `backend/ai/identity/session-bootstrap.md`, including that identity grants no execution/write authority.
- [ ] Document backend-owned harness lifecycle: intent inference, permission gates, target resolution, harness execution, harness-result injection or deterministic rendering, persistence, and follow-up resolution.
- [ ] Document provider-native toolcalling as a future adapter path, not the primary path for this change.
- [ ] Document response policies/templates and where to edit them.
- [ ] Document Raven/write boundaries: model must not directly write to Raven, SQLite, Neo4j, Postgres, CMDB, or operational systems.
- [ ] Optionally add a short link from `backend/ai/README.md` to policies, templates, and `docs/ai.md` if it does not push the slice over budget.

## Validation Commands

- [ ] Install backend test dependencies if needed: `cd backend && python -m pip install -r requirements.txt -r requirements-dev.txt`
- [x] Run focused backend tests during development: `cd backend && python -m pytest backend/tests/test_ai_chat_service.py`
- [ ] Run full backend tests before review: `cd backend && python -m pytest`
- [x] If frontend was not changed, no frontend test is required; if frontend chat UI changes are introduced unexpectedly, run `cd frontend && corepack pnpm test:run`.

## Rollback Boundaries

- [x] Slice A rollback: remove or disable the exact deterministic branch for `event_list`, `availability_check`, and `availability_check_batch`; keep markdown files as inert documentation if desired; existing LM Studio and fallback paths should continue to work.
- [ ] Slice B rollback: revert `docs/ai.md` and optional README link only; no runtime behavior should be affected.
