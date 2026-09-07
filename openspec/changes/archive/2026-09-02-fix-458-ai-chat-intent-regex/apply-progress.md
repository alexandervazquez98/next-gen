# Apply Progress: fix-458-ai-chat-intent-regex

**Change**: `fix-458-ai-chat-intent-regex`
**Apply batch**: 1 (first apply batch)
**Request ID**: `apply-fix-458-v1`
**SDD attempt token**: `sha256:2aee3ccc03771c6f1889936e5e135a6243899df8bb9918d484de409f22c91052`
**Mode**: Strict TDD
**Date**: 2026-09-02

## Workload decision

- Delivery strategy: `ask-on-risk` (Low risk → no decision gate needed)
- Chain strategy: N/A (single PR)
- Estimated budget: ~95 changed lines (forecast Low)
- Final diff: 103+/4- = **107 changed lines** (under 150 bound)

## Files changed

| File | Action | LOC delta |
|------|--------|-----------|
| `backend/routers/ai.py` | Modified | +12/-2 |
| `backend/tests/test_ai_chat_service.py` | Modified | +89/0 |
| `backend/ai/policies/followup-intents.md` | Modified | +2/-2 |

Total: **+103/-4 = 107 lines** — within 150-line bound, within 400-line review budget.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `backend/tests/test_ai_chat_service.py` | Unit (parametrized x5) | 4/4 baseline passed | 5 cases FAILED with old regex | ✅ 5 cases PASS | ✅ 5 different stems (verificación/verificando/monitoreando/chequeando/check) | N/A |
| 1.2 | `backend/tests/test_ai_chat_service.py` | Unit (parametrized x2) | 4/4 baseline passed | Regression guard — passes both old/new regex; documents over-matching prevention | ✅ 2 cases PASS | ✅ tengo+tenemos | N/A |
| 1.3 | `backend/tests/test_ai_chat_service.py` | Unit (parametrized x4) | 4/4 baseline passed | 4 cases FAILED with old regex | ✅ 4 cases PASS | ✅ tengo+eventos/tenemos+alertas/cuáles+eventos/cuales+tenemos | N/A |
| 1.4 | `backend/tests/test_ai_chat_service.py` | Unit | 4/4 baseline passed | Regression guard — passes both old/new regex (no event marker gates AND) | ✅ 1 case PASS | ➖ Single regression | N/A |
| 2.1 | (production) `backend/routers/ai.py` | — | — | — | ✅ regex widened | — | Multiline grouped by family |
| 2.2 | (production) `backend/routers/ai.py` | — | — | — | ✅ regex widened | — | Multiline grouped by family |
| 3.1 | (audit only) | — | — | — | — | — | Patterns already grouped by stem family (verific/chequ/revis/monitor/comprob/consult + canonicals); multiline is more readable than single long alternation — kept as-is |

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `cd backend && python -m pytest tests/test_ai_chat_service.py -k "intent or followup" -q` → **16 passed** (5 parametrized stems + 2 negative + 4 parametrized event-list + 1 tengo-no-marker + 4 existing followup regressions) |
| Runtime harness command/scenario | N/A — pure unit/inference helpers; no live collector or HTTP integration boundary in scope. Existing integration coverage (`test_followup_availability_batch_uses_latest_event_list_context` line 1273) covers the end-to-end router path and remained GREEN. |
| Rollback boundary | Revert the two regex literals in `backend/routers/ai.py` (one-commit revert). Tests self-revert. No schema/persistence/downstream change. |

## Tasks completed

- [x] 1.1 Add `test_infer_followup_availability_recognizes_spanish_stems` (5 parametrized stems)
- [x] 1.2 Add `test_infer_followup_availability_rejects_event_list_only_phrasings` (2 parametrized negative cases)
- [x] 1.3 Add `test_infer_chat_intent_recognizes_event_list_phrasings` (4 parametrized phrasings)
- [x] 1.4 Add `test_infer_chat_intent_rejects_tengo_without_event_marker` (negative case)
- [x] 1.5 Confirm RED on `intent or followup` filter
- [x] 2.1 Widen `asks_to_list` regex (added `tengo(s)?|tenemos|cu[aá]les?`)
- [x] 2.2 Widen `asks_availability` regex (added 12 stem families)
- [x] 2.3 Confirm RED→GREEN + existing tests at lines 1200, 1273, 1324, 1431 still pass
- [x] 3.1 Refactor audit — kept multiline grouping (already clean)
- [x] 4.1 Update `backend/ai/policies/followup-intents.md` (mirrors broadened triggers)
- [x] 5.1 Full backend pytest: `tests/test_ai_chat_service.py` 91/91 GREEN; full suite 1978 pass + 6 pre-existing failures (verified unrelated on clean `main`)

## Deviations from design

| Deviation | Reason |
|-----------|--------|
| `asks_to_list` regex adds explicit `tenemos` alternative (design had `tengo(s)?` which only matches `tengo` or `tengos`) | The Spanish verb "tenemos" (we have) is not captured by the design pattern `tengo(s)?`. To satisfy spec scenarios for `tenemos alertas abiertas` and `cuales eventos tenemos`, the regex was expanded to `tengo(s)?\|tenemos\|cu[aá]les?`. Minimal one-token addition. |

No other deviations. All other design decisions (stem families, accent handling, doc sync) implemented as specified.

## Risks encountered

None during apply. Pre-existing failures in `tests/test_auth_router_refresh.py::TestCookieDomainAndSecure` and `tests/test_writer_advisory_lock.py` are unrelated to this change and reproduce on clean `main`.

## Status

**11/11 tasks complete.** Ready for `sdd-verify`.
