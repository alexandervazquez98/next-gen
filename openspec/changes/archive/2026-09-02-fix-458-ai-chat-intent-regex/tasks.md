# Tasks: fix-458-ai-chat-intent-regex

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~95 (4-10 LOC code + ~80 LOC tests + ~5 LOC doc) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Broaden `asks_availability` + `asks_to_list` regexes with stem-based alternations and doc sync | PR 1 | `cd backend && python -m pytest tests/test_ai_chat_service.py -k "intent or followup or event_list" -q` | N/A — pure unit/inference helpers; no live collector required | Revert `backend/routers/ai.py` (two regex literals) + `backend/ai/policies/followup-intents.md`; tests self-revert |

## Phase 1: RED — Failing parametrized tests (strict TDD)

- [x] 1.1 Add `test_infer_followup_availability_recognizes_spanish_stems` parametrized over `["verificación", "verificando", "monitoreando", "chequeando", "check"]` asserting `infer_followup_intent` returns truthy for each in `backend/tests/test_ai_chat_service.py`.
- [x] 1.2 Add `test_infer_followup_availability_rejects_event_list_only_phrasings` asserting `tengo` and `tenemos` (no availability verb) yield `asks_availability` falsy on a stubbed DB returning empty `ci_refs`.
- [x] 1.3 Add `test_infer_chat_intent_recognizes_event_list_phrasings` parametrized over `["tengo eventos críticos", "tenemos alertas abiertas", "cuáles son los eventos", "cuales eventos tenemos"]` asserting `infer_chat_intent` returns a `event_list` intent.
- [x] 1.4 Add `test_infer_chat_intent_rejects_tengo_without_event_marker` asserting `"tengo una pregunta"` returns `None`.
- [x] 1.5 Run `cd backend && python -m pytest tests/test_ai_chat_service.py -k "intent or followup" -q` and confirm all new cases fail (RED).

## Phase 2: GREEN — Loosen regex literals

- [x] 2.1 In `backend/routers/ai.py:120-123` widen `asks_to_list` regex per design §Interfaces: keep existing tokens, append `tengo(s)?|tenemos|cu[aá]les?` (added explicit `tenemos` because design's `tengo(s)?` does not match the `tenemos` verb form).
- [x] 2.2 In `backend/routers/ai.py:150-153` widen `asks_availability` regex per design §Interfaces: keep canonical tokens, add stems `verific\w*|verifiqu\w*|chequ\w*|chec\w*|revis\w*|revisi\w*|revisa\w*|monitor\w*|monitore\w*|comprueb\w*|comprob\w*|consult\w*`.
- [x] 2.3 Run `cd backend && python -m pytest tests/test_ai_chat_service.py -k "intent or followup" -q` and confirm RED→GREEN; rerun full file to confirm lines 1200, 1273, 1324, 1431 still pass.

## Phase 3: REFACTOR — Clean-up

- [x] 3.1 Audit widened patterns for readability; collapse to single alternation if multiline sprawl hurts review; rerun tests. → Patterns already grouped by stem family (verific/chequ/revis/monitor/comprob/consult + canonicals). Multiline grouping is more readable than a single long alternation, so kept as-is. Rerun `intent or followup` suite confirms 16/16 GREEN.

## Phase 4: Doc sync

- [x] 4.1 Update `backend/ai/policies/followup-intents.md` §Availability follow-up triggers to list the new stems (`verific*`, `chequ*`, `monitor*`, `revis*`, `comprob*`, `consult*`) and §Event-list triggers to add `tengo(s)?`, `cu[aá]les?`.

## Phase 5: Final verification

- [x] 5.1 Run `cd backend && python -m pytest` (full suite); confirm new cases green AND existing tests at lines 1200, 1273, 1324, 1431 stay green.
  - `tests/test_ai_chat_service.py`: **91 passed**
  - 4 critical regression tests at lines 1200, 1273, 1324, 1431 still GREEN
  - Full backend suite: **1978 passed, 6 pre-existing failures** in `test_auth_router_refresh.py::TestCookieDomainAndSecure` and `test_writer_advisory_lock.py` — verified on clean `main` that these 6 fail without my changes (unrelated to intent regex). Total diff: 103+/4- = 107 lines (under 150 bound).