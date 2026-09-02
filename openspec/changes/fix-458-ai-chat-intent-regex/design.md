# Design: fix-458-ai-chat-intent-regex

## Technical Approach

Stem-based regex widening on the two existing inference helpers in `backend/routers/ai.py`. Replace literal Spanish verb literals with `\w*` suffixed stems, add `tengo(s)?` and `cu[aá]les?` to `asks_to_list`, keep every canonical English/Spanish token unchanged. No new component, no new dependency, no schema or persistence change.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|---|---|---|---|
| Regex morphology strategy | (A) Stem prefix (`\w*`) / (B) Wordlist enumeration / (C) NLP stemmer | A is smallest diff, no dep, matches issue body. B is brittle. C adds 10s of MB. | **A** |
| Accent handling for `cuáles` | Single literal vs explicit `cu[aá]les?` | `re` engine is byte-level; explicit alternation is readable and stable for cross-locale reviewers. | Explicit `cu[aá]les?` |
| Where the new tokens live | Inline in `ai.py` vs shared module | Only two helpers consume them; no other consumers depend on these token sets. | Inline in `ai.py` |
| Doc sync | Edit policy file vs skip | `followup-intents.md` enumerates triggers in prose; skipping creates drift. | Edit policy file |

## Data Flow

    client query ──► infer_chat_intent ──[None]──► infer_followup_intent ──[None]──► free-text LM Studio
                          │                              │
                          ▼                              ▼
                   asks_to_list (regex)         asks_availability (regex)
                          │                              │
                          ▼                              ▼
                  AND asks_for_events         AND latest_event_list_ci_refs ≠ []
                          │                              │
                          ▼                              ▼
                   event_list harness          availability_check_batch harness

Both branches already return `None` when their AND-gate preconditions fail. Wider match surface widens entry to the regex; the AND gate remains the safety net.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/routers/ai.py` | Modify | Loosen `asks_to_list` (line 121) with `tengo(s)?`, `cu[aá]les?`, `cuales` stems; loosen `asks_availability` (line 151) with `verific*`, `verifiqu*`, `chequ*`, `chec*`, `monitor*`, `monitore*`, `comprueb*`, `comprob*`, `consult*` stems. Keep every existing canonical literal. |
| `backend/tests/test_ai_chat_service.py` | Modify | Add parametrized pytest cases for `verificación`, `verificando`, `monitoreando`, `chequeando`, `check`, `tengo`, `tenemos`, `cuáles` plus a negative case asserting `tengo`/`tenemos` alone do NOT trigger `asks_availability`. |
| `backend/ai/policies/followup-intents.md` | Modify | Doc sync — refresh the trigger list to mirror the broadened regex. |

No new files. No deletes.

## Interfaces / Contracts

No public interface change. `infer_chat_intent(query) -> AIChatIntent | None` and `infer_followup_intent(query, db, username) -> AIChatIntent | None` keep the same signature, same return shape, same AND-gated semantics. Only the regex literals inside change.

```python
# infer_chat_intent.asks_to_list (line 121)
asks_to_list = re.search(
    r"\b("
    r"list\w*|listar|lista|mostrar|muestra|ver|ves|detalle|detalla|"
    r"activos?|abiertos?|actuales?|"
    r"tengo(s)?|cu[aá]les?"
    r")\b",
    normalized,
)

# infer_followup_intent.asks_availability (line 151)
asks_availability = re.search(
    r"\b("
    r"verific\w*|verifiqu\w*|chequ\w*|chec\w*|"
    r"revis\w*|revisi\w*|revisa\w*|"
    r"monitor\w*|monitore\w*|"
    r"comprueb\w*|comprob\w*|consult\w*|"
    r"estatus|estado|siguen|sigue|funcionando|responden|"
    r"reachable|working|availability|disponibilidad"
    r")\b",
    normalized,
)
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | New tokens hit `asks_availability` | Parametrize `infer_followup_intent` with `verificación`, `verificando`, `monitoreando`, `chequeando`, `check`. Assert truthy. |
| Unit | New tokens hit `asks_to_list` (gated) | Parametrize `infer_chat_intent` with `tengo eventos`, `tenemos eventos`, `cuáles son los eventos`. Assert truthy. |
| Unit | Negative case | Assert `tengo` and `tenemos` alone do NOT trigger `asks_availability`. |
| Regression | Existing canonicals | Existing tests at lines 1200, 1273, 1324, 1431 must stay green. |
| Integration | Historical query IDs 48, 50 | Replay produces `harness_result.type == "availability_check_batch"` with `n_results > 0`. |

## Threat Matrix

N/A on routing, shell, subprocess, VCS/PR automation, executable-file classification, and process integration.

The single in-scope risk is **regex over-matching**. Mitigations already present in the codebase:

- `asks_to_list` widening is AND-gated by `asks_for_events` (`events?/eventos?/alertas?/incidentes?`). Conversational `tengo una pregunta` cannot route to event-list harness.
- `asks_availability` widening AND-gates by `latest_event_list_ci_refs(db, username, query)` returning a non-empty list. A user with no recent `event_list` harness result cannot trigger a synthetic `availability_check_batch` ping.
- Existing tests at 1200, 1273, 1324, 1431 cover canonical forms; new parametrized tests plus the `tengo`/`tenemos` negative case cover the widened surface.

No new RED tests required beyond the parametrized cases listed in the testing strategy.

## Migration / Rollout

No migration required. No schema, no persisted state, no config flag, no phased rollout. Deploy = standard backend release.

**Rollback**: revert the two regex literals in `backend/routers/ai.py` (one-commit revert). All downstream behaviour, persistence, and routing unchanged.

## Open Questions

None.
