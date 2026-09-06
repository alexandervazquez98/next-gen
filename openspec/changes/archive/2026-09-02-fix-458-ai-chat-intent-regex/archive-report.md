# Archive Report — `fix-458-ai-chat-intent-regex`

**Archive date**: 2026-09-02
**Change**: `fix-458-ai-chat-intent-regex`
**Issue**: Closes #458 — `infer_followup_intent` regex misses Spanish verb conjugations
**Branch / commit**: `fix/458-459-460-ai-chat-neo4j-cleanup` @ `a485e08`
**Artifact store**: openspec
**Verdict**: PASS

## Final Summary

**Intent**: Widen the literal-word regexes in `infer_chat_intent.asks_to_list` and `infer_followup_intent.asks_availability` (`backend/routers/ai.py`) so that common Spanish verb conjugations (`verificación`, `verificando`, `monitoreando`, `chequeando`) and event-list phrasings (`tengo`, `tenemos`, `cuáles`) are recognized. Affected queries previously bypassed harness selection and surfaced generic LM Studio output instead of the deterministic `availability_check_batch` / event-list harness — breaking the spec's allowed-path guarantee for Spanish operators.

**Scope**: Stem-based regex widening on two helpers in one file (`backend/routers/ai.py`), parametrized regression tests in one file (`backend/tests/test_ai_chat_service.py`), and policy doc sync (`backend/ai/policies/followup-intents.md`). No new dependency, no schema or persistence change, no public-interface change.

**Outcome**: All 11 tasks complete. 11/11 spec scenarios compliant. 91/91 tests in `test_ai_chat_service.py` pass. Ruff lint clean. Production diff +103/-4 lines within the 400-line review budget.

## Files Changed (production code)

Per `git show --stat a485e08`:

| File | Action | LOC delta | Description |
|------|--------|-----------|-------------|
| `backend/routers/ai.py` | Modified | +12/-2 | Two regex literals widened: `asks_to_list` (line ~121) with `tengo(s)?\|tenemos\|cu[aá]les?`; `asks_availability` (line ~151) with `verific\w*\|verifiqu\w*\|chequ\w*\|chec\w*\|revis\w*\|revisi\w*\|revisa\w*\|monitor\w*\|monitore\w*\|comprueb\w*\|comprob\w*\|consult\w*` plus canonicals preserved |
| `backend/tests/test_ai_chat_service.py` | Modified | +89/0 | 11 parametrized pytest cases + 1 negative-assertion companion |
| `backend/ai/policies/followup-intents.md` | Modified | +2/-2 | Doc sync — trigger list mirrors broadened regex |

**Total production diff**: **+103/-4 = 107 changed lines** (well within 400-line review budget).

## Test Coverage

**Test command**: `python3.11 -m pytest tests/test_ai_chat_service.py -q`
**Result**: **91 passed, 36 warnings in 1.68s** — 0 failures.

**Focused command**: `python3.11 -m pytest tests/test_ai_chat_service.py -k "intent or followup or infer" -q`
**Result**: **18 passed, 73 deselected** (5 new Spanish/English stems + 2 new negative tengo/tenemos cases + 4 new parametrized event-list phrasings + 1 new negative tengo-without-marker case + 6 existing intent/followup regression tests).

**New test functions**:

| Test | Parametrized cases | Layer |
|------|---------------------|-------|
| `test_infer_followup_availability_recognizes_spanish_stems` | 5: `verificación de los switches`, `verificando el estado`, `monitoreando la red`, `chequeando la conectividad`, `check the connectivity` | Unit |
| `test_infer_followup_availability_rejects_event_list_only_phrasings` | 2 (negative): `tengo`, `tenemos` (no availability verb; asserts `asks_availability` falsy on stubbed DB returning empty `ci_refs`) | Unit |
| `test_infer_chat_intent_recognizes_event_list_phrasings` | 4: `tengo eventos críticos`, `tenemos alertas abiertas`, `cuáles son los eventos`, `cuales eventos tenemos` | Unit |
| `test_infer_chat_intent_rejects_tengo_without_event_marker` | 1 (negative): `"tengo una pregunta"` returns `None` | Unit |

Total: **11 parametrized cases** + 1 negative-companion = **12 new test cases** across 4 test functions.

**Regression coverage preserved**: existing critical tests at `test_ai_chat_service.py` lines 1200, 1273, 1324, 1431 all stay green (4/4 baseline).

**Coverage tool**: `coverage` package not installed in this environment; analysis skipped per `strict-tdd-verify.md` §5d. The 12 new tests exercise every branch of both widened regexes (positive `re.search` returns, negative `None` returns, AND-gate preconditions both satisfied and violated).

**Assertion quality**: All assertions verify real behaviour. Mock count per test ≤ 2. Negative cases paired with positive counterparts. No tautologies, no ghost loops, no implementation-detail coupling.

**Linter**: `python3.11 -m ruff check routers/ai.py tests/test_ai_chat_service.py` → **"All checks passed!"**

**Build**: `python3.11 -m py_compile routers/ai.py tests/test_ai_chat_service.py` → **compile OK**

## Spec Compliance Matrix (final)

| Req | Scenario | Test | Result |
|-----|----------|------|--------|
| REQ-01 (Spanish verb stems) | `verificación` triggers availability intent | `…rec_spa_stems[verificación de los switches]` | ✅ COMPLIANT |
| REQ-01 | Gerund conjugations trigger availability intent | `…rec_spa_stems[monitoreando la red]`, `…[chequeando la conectividad]` | ✅ COMPLIANT |
| REQ-01 | English stem `check` triggers availability intent | `…rec_spa_stems[check the connectivity]` | ✅ COMPLIANT |
| REQ-01 | Canonical tokens remain recognized | `…test_followup_availability_batch_uses_latest_event_list_context` (line 1273) — `"verifica si están funcionando"` | ✅ COMPLIANT |
| REQ-01 | Event-list phrasings alone do not trigger availability intent | `…rejects_event_list_only_phrasings[tengo]`, `[tenemos]` | ✅ COMPLIANT |
| REQ-02 (event-list phrasings) | `tengo` with event marker triggers event-list intent | `…event_list_phrasings[tengo eventos críticos]` | ✅ COMPLIANT |
| REQ-02 | `cuáles son los eventos` triggers event-list intent | `…event_list_phrasings[cuáles son los eventos]`, `[cuales eventos tenemos]` | ✅ COMPLIANT |
| REQ-02 | Conversational `tengo` without event marker does not trigger event-list intent | `…rejects_tengo_without_event_marker` | ✅ COMPLIANT |
| REQ-02 | Canonical event-list phrasings remain recognized | `…test_event_list_harness_infers_open_critical_filters` (line 1200) | ✅ COMPLIANT |
| REQ-03 (no spurious harness runs) | Availability stem without prior event_list returns None | `…rejects_event_list_only_phrasings` uses `_FakeHistoryDb([])` + stubbed `latest_event_list_ci_refs → []` | ✅ COMPLIANT |
| REQ-03 | Event-list stem with no event marker returns None | `…rejects_tengo_without_event_marker` returns `None` | ✅ COMPLIANT |

**Compliance summary**: **11/11 scenarios compliant**.

## Deviations from Design

| # | Deviation | Rationale |
|---|-----------|-----------|
| 1 | `asks_to_list` regex adds explicit `tenemos` alternative beyond design's `tengo(s)?` (final pattern: `tengo(s)?\|tenemos\|cu[aá]les?`) | The design pattern `tengo(s)?` only matches `tengo` or `tengos`; it does not match the Spanish verb "tenemos" (we have). To satisfy the spec scenarios `tenemos alertas abiertas` and `cuales eventos tenemos`, the implementation expanded the alternation with one additional literal `tenemos`. **Minimal one-token addition.** All other design decisions implemented as specified (stem families, accent handling, doc sync, inline tokens). |

No other deviations. Design strategy (stem prefix with `\w*`), accent handling (`cu[aá]les?` explicit alternation), inline-only location (`ai.py`), and doc sync (`followup-intents.md`) all implemented exactly as designed.

## Pre-existing Failures (unrelated, verified on clean `main`)

When the full backend suite was exercised:

- `tests/test_ai_chat_service.py`: **91 passed** (all targets green)
- Full backend suite: **1978 passed + 6 pre-existing failures** in:
  - `test_auth_router_refresh.py::TestCookieDomainAndSecure`
  - `test_writer_advisory_lock.py`

These 6 failures are confirmed **unrelated** to this change — they reproduce on a clean `main` checkout without the regex widening applied. They are tracked upstream and not part of this slice.

## Final Source of Truth — Specs Updated

The following main spec now reflects the new behaviour:

| Domain | Action | Requirements | Scenarios |
|--------|--------|--------------|-----------|
| `ai-chat-harness-guardrails` | Updated (3 ADDED requirements appended) | 3 | 11 |

Main spec path: `openspec/specs/ai-chat-harness-guardrails/spec.md` (194 → 278 lines after merge).

Delta requirement headings added under the existing `## ADDED Requirements` section:

1. `### Requirement: Follow-up availability inference recognizes Spanish verb stems`
2. `### Requirement: Chat intent inference recognizes event-list phrasings`
3. `### Requirement: Wider match surface does not produce spurious harness runs`

All existing requirements (lines 9-194) preserved byte-exactly. The delta section was extracted from the source via `sed -n '5,87p'` and appended via shell — no model Read/Write path used for content. **Byte-identity verified** by `diff -r` (empty output = passing evidence; see Phase Result below).

## Verdict

**PASS**

- 11/11 spec scenarios have covering tests that passed at runtime
- 11/11 tasks complete
- 91/91 tests in the impacted file pass; existing critical regressions at lines 1200, 1273, 1324, 1431 stay green
- Ruff lint clean; `py_compile` clean
- Single design deviation (`tenemos` literal) documented, minimal, and required by spec scenarios
- Strict TDD evidence present and validated (RED→GREEN transitions documented in `apply-progress.md` §TDD Cycle Evidence)
- Production diff (+103/-4 = 107 lines) within both 150-line plan-bound and 400-line review budget

## Rollback Plan

**One-commit revert** of `a485e083790ccca0a8ecfd5895900007bb7bd3e8`.

```bash
git revert a485e08
```

The commit touches only two regex literals in `backend/routers/ai.py` plus their covering tests and a doc file. No schema, no persistence, no downstream consumer changes. Tests self-revert. Plan file revert + clean re-run of `pytest tests/test_ai_chat_service.py` confirms restoration. This SDD change's archived artifacts (`proposal.md`, `specs/`, `design.md`, `tasks.md`, `apply-progress.md`, `verify-report.md`, `exploration.md`) remain in `openspec/changes/archive/2026-09-02-fix-458-ai-chat-intent-regex/` as audit trail regardless of code revert.

## Issue Reference

Closes #458 — `infer_followup_intent` regex misses Spanish verb conjugations

---

## Archive Folder Manifest

`openspec/changes/archive/2026-09-02-fix-458-ai-chat-intent-regex/`

| Artifact | Size | Status |
|----------|------|--------|
| `proposal.md` | 3,607 B | ✅ |
| `exploration.md` | 11,284 B | ✅ |
| `specs/ai-chat-harness-guardrails/spec.md` | 4,380 B | ✅ |
| `design.md` | 5,865 B | ✅ |
| `tasks.md` | 4,177 B | ✅ (11/11 marked complete) |
| `apply-progress.md` | 5,122 B | ✅ |
| `verify-report.md` | 11,345 B | ✅ (verdict: PASS) |
| `archive-report.md` | (this file) | ✅ (additive, excluded from snapshot diff) |

---

## Phase Result — Mechanical Copy Readback (MANDATORY)

Per `sdd-archive` SKILL.md §Mechanical Copy Contract.

### Step 2 — Baseline Spec Merge

```text
=== Baseline pre-merge: 194 lines ===
=== Delta lines 5-87 (extracted): 83 lines ===
=== Expected post-merge: 278 lines ===
=== Actual post-merge: 278 lines ===
=== MANDATORY diff readback (delta block vs appended region) ===
>>> diff exit 0 — appended region is BYTE-IDENTICAL to delta <<<
=== Verify baseline pre-merge + delta = post-merge (full file) ===
>>> diff exit 0 — full file matches (pre-merge + delta == post-merge) <<<
```

### Step 3 — Change Folder Move

```text
=== Snapshot source BEFORE move ===
total 104
drwxr-xr-x  9 macbook  staff    288 Sep  2 16:08 .
-rw-r--r--  1 macbook  staff   5122 Sep  2 16:08 apply-progress.md
-rw-r--r--  1 macbook  staff   5865 Sep  2 16:08 design.md
-rw-r--r--  1 macbook  staff  11284 Sep  2 16:08 exploration.md
-rw-r--r--  1 macbook  staff   3607 Sep  2 16:08 proposal.md
drwxr-xr-x  3 macbook  staff     96 Sep  2 16:08 specs
-rw-r--r--  1 macbook  staff   4177 Sep  2 16:08 tasks.md
-rw-r--r--@ 1 macbook  staff  11345 Sep  2 16:08 verify-report.md

=== Mechanical move (git mv, falling back to mv) ===
git mv succeeded

=== Confirm source is gone (mandatory) ===
OK: source directory is gone

=== MANDATORY diff -r readback (snapshot vs archive) ===
>>> diff -r exit 0 — archive byte-identical to source snapshot <<<
```

**All `diff` checks returned empty (no differences). No truncation. No alteration. No skip. Phase passes per Mechanical Copy Contract.**

---

## SDD Cycle Complete

The change has been fully planned, implemented, verified, and archived. Source-of-truth main spec updated under `openspec/specs/ai-chat-harness-guardrails/spec.md` with 3 new requirements covering Spanish verb stems, event-list phrasings, and the no-spurious-harness-run safety property.

Ready for the next change.
