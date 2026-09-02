# Proposal: fix-458-ai-chat-intent-regex

## Intent

`infer_chat_intent.asks_to_list` and `infer_followup_intent.asks_availability` (`backend/routers/ai.py`) use literal-word regexes that miss Spanish conjugations (`verificación`, `verificando`, `monitoreando`, `chequeando`) and event-list phrasings (`tengo`, `tenemos`, `cuáles`). Affected queries bypass harness selection, fall through to free-text LM Studio, and surface generic "no harness result" output instead of the deterministic `availability_check_batch` / event-list harness — breaking the spec's allowed-path guarantee for Spanish operators.

## Scope

### In Scope
- Stem-based regex in `asks_availability` (`ai.py:151`) and `asks_to_list` (`ai.py:121`).
- Parametrized tests for `verificación`, `verificando`, `monitoreando`, `chequeando`, `check`, `tengo`, `tenemos`, `cuáles`, plus a negative case ensuring `tengo`/`tenemos` alone do not trigger `asks_availability`.
- Doc sync in `backend/ai/policies/followup-intents.md`.

### Out of Scope
- New NLP dependency (no `spacy`/`snowballstemmer`).
- Changes to `latest_event_list_ci_refs`, `maybe_run_harness`, `HARNESS_EXECUTORS`, `complete_chat`, guardrail wiring, routing, prompt templates, LM Studio config.

## Capabilities

> Contract with `sdd-spec`. Each entry produces a delta spec under `openspec/changes/fix-458-ai-chat-intent-regex/specs/`.

### New Capabilities
None.

### Modified Capabilities
- `ai-chat-harness-guardrails`: add requirement that intent inference MUST recognize Spanish verb stems (verific*, chequ*, monitor*, revis*, comprob*, consult*) and event-list phrasings (`tengo(s)?`, `cu[aá]les?`); add regression scenario covering the conjugations above.

## Approach

Adopt the stem-based regex from issue #458 §Proposed Fix on both helpers. Behaviour for existing canonical tokens preserved; no new dependency. `infer_followup_intent` already returns `None` when `latest_event_list_ci_refs` finds no prior `event_list`, so the wider match surface cannot trigger a synthetic ping without context.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/routers/ai.py` | Modified | Stem-based alternation in `asks_availability` (~line 151) and `asks_to_list` (~line 121). |
| `backend/tests/test_ai_chat_service.py` | Modified | Parametrized cases for new tokens + one negative case. |
| `backend/ai/policies/followup-intents.md` | Modified | Doc sync — trigger list mirrors the regex. |

## Risks

| Risk | Mit |
|------|-----|
| False positives broaden match surface | `infer_followup_intent` returns `None` without prior event list; no spurious harness run. |
| `tengo`/`tenemos` over-match in `asks_to_list` | Still requires `asks_for_events` AND `asks_to_list` together. |
| Accent variants (`cuáles` vs `cuales`) | Both literal forms in alternation. |
| Doc drift | Edit `followup-intents.md` in the same change. |

## Rollback Plan

Revert the two regex literals in `backend/routers/ai.py` to their pre-fix shapes (one-commit revert). No schema, persistence, or downstream changes, so rollback is safe.

## Dependencies

None. No new libraries, migrations, or external services.

## Success Criteria

- [ ] New parametrized tests pass; existing tests at lines 1200, 1273, 1324, 1431 stay green.
- [ ] Affected historical queries (IDs 48, 50, similar) produce `harness_result.type == "availability_check_batch"` with `n_results > 0`.
- [ ] Delta spec added under `specs/ai-chat-harness-guardrails/`; `followup-intents.md` updated.
- [ ] Net diff under 400 changed lines (estimate: ~15 LOC code + ~80 LOC tests).
