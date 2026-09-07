# Exploration: fix-458-ai-chat-intent-regex

## 1) Current State

The `/api/ai/chat` route (`backend/routers/ai.py`) is the only entry point for AI chat. Intent selection runs entirely in backend code; the LM Studio model only fills **content** once a `harness_result` is in hand.

When the client omits `intent`, the router calls two **heuristic** regex-based inference helpers, in order:

1. `infer_chat_intent(query)` (line 111) — detects **event-list** intent from queries like "lista los eventos abiertos".
2. `infer_followup_intent(query, db, username)` (line 147) — when no chat intent is matched, detects a **follow-up availability batch** against the user's most recent `event_list` harness result.

Both helpers use literal-word regexes. Conjugated Spanish variants slip through and the request falls through to a free-text LM Studio call, which returns a generic "no harness result" apology.

### Current regex behaviour (verified by direct regex probe)

`infer_followup_intent` `asks_availability` (line 151):
```
\b(verifica|verificar|checa|chequeo|revisa|revisar|estatus|estado|siguen|
  disponibilidad|funcionando|responden|reachable|working|availability)\b
```

Probe results against the literal pattern:

| Probe query                       | Matched? | Triggered verb      |
| --------------------------------- | -------- | ------------------- |
| `ejecuta una verificacion de todos` | NO       | — (literal `verifica`/`verificar` only) |
| `verificación de los switches`     | NO       | — |
| `verificando el estado`            | YES      | `estado` (incidental) |
| `monitoreando los equipos`         | NO       | — |
| `chequeando la red`                | NO       | — |
| `check`                            | NO       | — |

`infer_chat_intent` `asks_to_list` (line 121):
```
\b(list|listar|lista|mostrar|muestra|ver|ves|detalle|detalla|
  activos?|abiertos?|actuales?)\b
```

| Probe query                       | Matched? |
| --------------------------------- | -------- |
| `cuantos eventos con ACK tenemos?`| NO       |
| `cuáles son los eventos?`         | NO       |
| `tenemos eventos críticos?`       | NO       |
| `que eventos abiertos tenemos`    | YES (`abiertos`) |
| `lista los eventos abiertos`      | YES (`lista` + `abiertos`) |

### Impact of the misses

- `infer_followup_intent` returns `None` for queries that clearly ask for an availability check after a recent event list (e.g. `ejecuta una verificacion de todos`, `monitoreando`, `chequeando`, `check`).
- Without an intent, `chat_with_ai` bypasses `maybe_run_harness` and falls back to a free-text LM Studio call (`complete_chat`). Because no `harness_result` is produced, the deterministic render path in `services/ai_chat_service.complete_chat` is skipped, and `synthesize_harness_fallback_response` returns `None` for the empty `harness_result`, so the response is whatever the upstream LM Studio (default `qwen/qwen3.5-9b`) returns — typically an apology.
- Affected query IDs 48, 50 (and similar) end with `harness_result.type == None` and `model == "qwen/qwen3.5-9b"` instead of the expected `availability_check_batch` with `n_results > 0`.

### Downstream coupling

- `latest_event_list_ci_refs` (`services/ai_chat_service.py:621`) already accepts conjugations via its `_normalized_terms` tokenizer (e.g. `verificación`, `monitoreando` would be tokenized today), so once the intent is inferred, follow-up CI resolution already works for affected queries.
- The followup intent's only output is `AvailabilityBatchIntent(type="availability_check_batch", ci_refs=ci_refs)`. The router already has a complete batch path including guard evaluation, canonical CI resolution, bounded pings, deterministic render, and `record_operation` — none of which need to change.
- `HARNESS_EXECUTORS["availability_check_batch"]` (`services/ai_chat_service.py:528`) reuses the single-CI `_run_availability_harness`, so no executor changes are needed.
- The proposed regex update targets **only** `infer_chat_intent`'s `asks_to_list` and `infer_followup_intent`'s `asks_availability`. No other consumers depend on these specific token sets.

### Existing test coverage

`backend/tests/test_ai_chat_service.py` already exercises:

- `test_followup_availability_batch_uses_latest_event_list_context` (line 1273) — query `"verifica si están funcionando"` (a literal canonical form).
- `test_followup_status_filters_latest_event_list_by_named_area` (line 1324) — `"dame el estatus actual de islas agrarias, como sigue el sitio?"` (also canonical).
- `test_followup_confirmation_runs_availability_batch_from_recent_event_list` (line 1431) — `"sí"` confirmation.
- `test_event_list_harness_infers_open_critical_filters` (line 1200) — `"lista todos los eventos abiertos criticos"` (covers canonical `lista`/`abiertos`).
- No tests cover conjugated variants like `verificación`, `verificando`, `monitoreando`, `chequeando`, `check`, `tengo`, `tenemos`, `cuáles`.

## 2) Affected Areas

- `backend/routers/ai.py` — `infer_chat_intent` (`asks_to_list` regex at line 121) and `infer_followup_intent` (`asks_availability` regex at line 151). **The only production source change.**
- `backend/tests/test_ai_chat_service.py` — add parametrized cases for the missing conjugations and one negative case (e.g. `tengo` / `tenemos` should NOT trigger `asks_availability` because they are event-list phrasings, not availability).
- `backend/ai/policies/followup-intents.md` — refresh human-facing trigger list to match the broadened pattern (documentation alignment, low risk).
- No change to `latest_event_list_ci_refs`, `maybe_run_harness`, `HARNESS_EXECUTORS`, `complete_chat`, `synthesize_harness_fallback_response`, guardrail wiring, or HTTP routing.

## 3) Approaches

### Option A — Stem-based regex (recommended, matches issue body)

Replace the literal alternation with prefix stems for the Spanish verb families while keeping exact English triggers.

```python
asks_availability = re.search(
    r"\b("
    r"verific\w*|verifiqu\w*|"
    r"chequ\w*|chec\w*|"
    r"revis\w*|revisi\w*|revisa\w*|"
    r"monitor\w*|monitore\w*|"
    r"comprueb\w*|comprob\w*|"
    r"consult\w*|"
    r"estatus|estado|siguen|sigue|funcionando|responden|"
    r"reachable|working|availability|disponibilidad"
    r")\b",
    normalized,
)
```

- **Pros**: Minimal footprint (single regex update + tests); covers the conjugations called out in the issue (`verificación`, `verificando`, `monitoreando`, `chequeando`, `check`); preserves exact-match behaviour for every existing canonical token.
- **Cons**: Wider net increases the chance of false positives. Mitigated by `latest_event_list_ci_refs` returning `[]` when there is no matching prior `event_list`, in which case the function still returns `None` — no spurious harness runs.
- **Effort**: Low (~15 LOC + ~80 LOC tests).

### Option B — Wordlist extension (literal alternation only)

Add every Spanish conjugation manually (`verificación`, `verificando`, `monitoreando`, `chequeando`, `checar`, `chequeado`, …).

- **Pros**: Even narrower match surface; explicit enumeration.
- **Cons**: Brittle (need to enumerate every future conjugation); larger alternation; identical byte-cost risk via `re` engine; no meaningful advantage over Option A.
- **Effort**: Low–Medium (similar LOC, but recurring maintenance).

### Option C — Linguistic stemmer (e.g. `nltk`, `spacy`, `snowballstemmer`)

Run a full Spanish/English stemmer pipeline before regex matching.

- **Pros**: Recovers morphology systematically.
- **Cons**: New runtime dependency on an NLP library; significant weight (10s of MB for spaCy) for a single inference path; breaks the lightweight, deterministic "regex only" character of the intent layer; must be pinned to a small model and audited.
- **Effort**: High (dependency, lazy-load, test surface).

## 4) Recommendation

**Option A**: stem-based regex, exactly as proposed in the issue body, applied to both `asks_availability` and `asks_to_list` with the same loosening treatment (add `tengo(s)?|cu[aá]les?` style extensions where exact-word list is the current shape).

Rationale:

- Matches the proposed-fix section of the issue verbatim, so it satisfies issue #458 acceptance criteria one-for-one.
- Smallest plausible diff: ~4 lines changed in `ai.py` and a parametrized test for each new token. Review budget (400 changed lines) is comfortable.
- Stays within the project's current regex-only intent style; no new third-party deps, no behavioural surprises for `complete_chat`/`synthesize_harness_fallback_response`.
- The followup path already fails safely (returns `None` → no harness) when there is no prior event list, so the wider net cannot run a synthetic ping.
- All existing tests at lines 1273, 1324, 1431, 1200 continue to pass because the broadened regex still matches every canonical token the existing tests rely on (`verifica`, `chequeo`, `revisa`, `estatus`, `estado`, `siguen`, `lista`, `abiertos`, `mostrar`, etc.).

## 5) Risks

- **False positives for availability lookalikes.** Phrases like "monitor this dashboard" or "check the logs" no longer need an availability intent to trigger the batch harness. Mitigation: `infer_followup_intent` already returns `None` when `latest_event_list_ci_refs` finds no prior matching event list — without a recent event list the broader match is inert.
- **Over-matching in `asks_to_list`.** Adding `tengo`/`tenemos` could route conversational phrasings ("tengo una pregunta") to event-list harness. Mitigation: `infer_chat_intent` still requires `asks_for_events` AND `asks_to_list` together, so only queries that already mention `evento(s)`/`events`/`alertas`/`incidentes` will be redirected.
- **Accent variants.** `cuáles` vs `cuales` — the regex is run against `query.lower()`, so accented forms collide with unaccented forms in Python `re` only if both are listed. Mitigation: include both `cuáles` and `cuales` in the alternation or rely on `re.IGNORECASE` — recommend explicit two-token entry to keep pattern stable for cross-locale reviewers.
- **Doc drift.** `backend/ai/policies/followup-intents.md` enumerates the trigger list in prose; without an edit it will drift from the regex. Mitigation: small documentation edit in the same change.
- **Review-budget safety.** Net change is well under 400 lines (the regex + new parametrized tests). No chained-PR strategy needed.

## 6) Ready for Proposal

**Yes.**

The orchestrator can proceed to `sdd-propose` for `fix-458-ai-chat-intent-regex`. Scope: a single narrow change touching one regex in `infer_chat_intent`, one in `infer_followup_intent`, and parametrized test additions in `backend/tests/test_ai_chat_service.py`. Optional, but low-cost: update `backend/ai/policies/followup-intents.md` to keep prose in sync.

Acceptance criteria from issue #458 that the design must satisfy:

- New tests covering `verificación`, `verificando`, `monitoreando`, `chequeando`, `check`, `tengo`, `tenemos`, `cuáles`, plus the existing canonical forms.
- Affected historical queries (ID 48, 50, and similar) produce `harness_result.type = "availability_check_batch"` with `n_results > 0`.
- Existing tests in `backend/tests/test_ai_chat_service.py` remain green (regression).
