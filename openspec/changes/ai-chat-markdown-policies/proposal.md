# Proposal: AI Chat Markdown Policies, Templates, and Developer Manual

## Change ID

`ai-chat-markdown-policies`

## Summary

Move NEX-GEN AI chat operational behavior from scattered Python strings and free-form model interpretation into auditable markdown policies, deterministic response templates, and a developer-facing AI integration manual.

The change preserves the working backend harness flow while reducing unsupported model claims such as invented availability checks, RCA, congestion, power failure, or “resolved/optimal/stable” conclusions that are not proven by harness data.

## Motivation

Recent live LM Studio testing showed the current AI chat flow can execute backend tools correctly, but model output still has too much freedom:

- It correctly listed open events from `event_list`, then over-interpreted symptoms as likely congestion, physical failure, power failure, or firewall issues.
- It previously claimed availability checks ran when no `harness_result` existed.
- Reasoning models may return empty `content` when `reasoning_content` consumes the token budget.
- Operational rules and response wording are split between Python code, existing tool docs, and model behavior.

The system needs a stricter, auditable contract:

- Backend tools/harnesses provide facts.
- Markdown policies describe what can and cannot be claimed.
- Deterministic templates render operational harness results.
- The model is used for conversational help only within bounded policy.
- Developers get one manual explaining LM Studio connection, identity, toolcalling, harnesses, and extension points.

## User-facing outcome

For operational questions such as:

```text
que eventos tenemos abiertos y cual es el diagnostico?
```

The assistant should answer from real `event_list` data in a bounded format:

```text
Hay 3 eventos abiertos.

Eventos observados:
- [WARNING / OPEN] CUMBRES_PTP_DIR_PLAYAS_DE_TIJUANA: Warning Threshold Breached: 128.0 >= 100.0
- [INFO / OPEN] SWITCH ESTANCIA INFRACTORES: Service/Host Down: PING-CHECK-CISCO
- [INFO / OPEN] SWITCH C2: Service/Host Down: PING-CHECK-CISCO

Diagnóstico observado:
- CUMBRES presenta una alerta de latencia ICMP sobre umbral WARNING.
- SWITCH ESTANCIA INFRACTORES y SWITCH C2 presentan eventos de disponibilidad tipo ping-check.

Límites:
- event_list no confirma causa raíz.
- No confirma congestión, energía, cableado, firewall, resolución ni cierre del evento.

Siguiente chequeo sugerido:
- Ejecutar availability_check sobre los CIs con eventos de disponibilidad.
- Revisar métricas históricas para el CI con latencia.
```

For availability checks, the assistant should distinguish current ping reachability from service health or event closure:

```text
Chequeo de disponibilidad ejecutado sobre 3 CIs:
- AP01-ISLAS_AGRARIAS-BAJA01: reachable, 4.29 ms, target 10.53.13.34
- AP02-ISLAS_AGRARIAS-BAJA01: reachable, 4.26 ms, target 10.53.13.35
- ISLAS_AGRARIAS_PTP_DIR_C4_MEXICALI: reachable, 4.86 ms, target 10.3.152.69

Interpretación permitida:
- Los 3 CIs respondieron al ping acotado en este momento.

Límites:
- Esto no confirma salud completa del servicio, RCA ni cierre automático de eventos.
```

## Scope

### In scope

1. Add markdown policy files under `backend/ai/policies/`:
   - `response-boundaries.md`
   - `lmstudio-runtime.md`
   - `followup-intents.md`

2. Add deterministic markdown template files under `backend/ai/templates/`:
   - `event_list.md`
   - `availability_check.md`
   - `availability_check_batch.md`

3. Add developer manual at:
   - `docs/ai.md`

4. Update backend rendering behavior so harness-backed operational responses use deterministic template output for:
   - `event_list`
   - `availability_check`
   - `availability_check_batch`

5. Preserve backend-owned harness execution:
   - no model-native tool execution as the primary path;
   - backend validates permissions;
   - backend resolves CI targets from stored CMDB data;
   - backend stores `harness_result` for follow-up references.

6. Keep LM Studio integration provider-neutral:
   - continue using OpenAI-compatible `/v1/chat/completions`;
   - backend-managed history remains the default;
   - document why native LM Studio stateful chat is not the default path.

7. Add tests that verify:
   - deterministic outputs include observed harness facts;
   - deterministic outputs do not contain unsupported RCA claims;
   - no-harness requests still warn the model not to claim tool execution;
   - existing event list and availability follow-up behavior remains intact.

### Manual content required

`docs/ai.md` must be developer-facing and cover:

- How to connect LM Studio:
  - required env vars;
  - `/v1/chat/completions` base URL;
  - model, timeout, max token, context-length considerations;
  - common LM Studio reasoning-model issues such as empty `content` and populated `reasoning_content`.
- Identity system:
  - `backend/ai/identity/Soul.md`;
  - `scope.md`;
  - `context-policy.md`;
  - `session-bootstrap.md`;
  - how identity is loaded and bounded.
- Toolcalling and harness model:
  - difference between provider-native tool calling and backend-owned harnesses;
  - current NEX-GEN choice: backend harnesses first;
  - future adapter path for OpenAI/Gemini/Ollama/LM Studio-compatible tools.
- Harness execution lifecycle:
  - intent inference;
  - permission checks;
  - CI target resolution;
  - harness execution;
  - `Harness result` injection;
  - deterministic template response;
  - history persistence and follow-up resolution.
- Derivative policies:
  - response boundaries;
  - no invented tool results;
  - no unsupported RCA;
  - reachable/unreachable semantics;
  - Raven boundary/no direct model writes.

### Out of scope

- Switching from `/v1/chat/completions` to LM Studio native `/api/v1/chat`.
- Making provider-native tool calling the primary execution path.
- Allowing the model to execute tools directly.
- Removing or weakening permission gates.
- Adding writes to Raven, SQLite, Neo4j, or Postgres from the model.
- Building a full markdown DSL with arbitrary control flow.
- Reworking frontend UX beyond what is needed to preserve existing chat flow.

## Proposed technical approach

### Markdown policies

Use markdown as the source of truth for human-auditable policy and examples.

Initial implementation should keep policy parsing intentionally small:

- read bounded markdown content from known paths;
- use files as documentation and optional prompt snippets;
- avoid complex runtime parsing unless a later design proves it is needed.

### Deterministic templates

For operational harness results, render deterministic responses in backend code using template files as the reviewed contract.

The renderer should:

- select template by `harness_result.type`;
- fill only known placeholders or render through a simple controlled formatter;
- fall back to safe built-in text if a template file is missing;
- never call LM Studio for the primary answer when deterministic harness rendering is selected.

The model can still be used for non-harness conversational questions and possibly for explicitly requested free-form analysis, but not to rewrite raw operational facts into unsupported RCA.

### Intent policy

Keep current Python/Pydantic schemas and regex inference for this slice. Document the trigger policy in `followup-intents.md` and add tests to keep implementation aligned.

A later slice may parse trigger terms from markdown if needed, but this proposal avoids making runtime behavior fragile during the first migration.

### LM Studio behavior

Document and preserve these rules:

- `/v1/chat/completions` is stateless and receives full message history from NEX-GEN backend.
- `LM_STUDIO_MAX_TOKENS` and `LM_STUDIO_TIMEOUT_SECONDS` must be tuned together.
- Reasoning models may return `reasoning_content` and empty `content`; deterministic harness rendering prevents operational failure for harness-backed requests.

## Acceptance criteria

- A developer can read `docs/ai.md` and understand how to connect LM Studio, edit identity, extend harnesses, and reason about toolcalling boundaries.
- Operational harness responses for event list and availability checks are deterministic or strictly templated.
- `event_list` answers no longer claim unconfirmed RCA, congestion, power, cabling, firewall, “optimal”, “stable”, “resolved”, or service health without evidence.
- `availability_check` answers clearly state bounded ping semantics.
- Existing tests for event filtering, follow-up resolution, permissions, history, and fallback continue passing.
- New tests cover markdown/template policy behavior and unsupported-claim prevention.
- No deployment to `.22` happens during implementation unless explicitly approved.

## Review workload forecast

Expected first implementation slice may touch:

- `backend/services/ai_chat_service.py`
- `backend/tests/test_ai_chat_service.py`
- `backend/ai/policies/*.md`
- `backend/ai/templates/*.md`
- `docs/ai.md`
- possibly `backend/ai/README.md`

Estimated changed lines: 300–650 depending on manual size.

Because the user selected a 400-line review budget, the design/tasks phase should split if needed:

1. PR/slice A: markdown policies/templates + deterministic renderer + tests.
2. PR/slice B: developer manual and README links.

If implementation forecast stays under 400 lines, a single PR is acceptable.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Template markdown becomes another source of truth but code diverges | Add tests asserting deterministic output semantics and forbidden claims. |
| Loading all markdown into LM Studio increases token pressure | Do not include all docs in every prompt; use deterministic rendering for harnesses. |
| Deterministic responses feel less conversational | Use clear, operator-friendly templates with concise interpretation sections. |
| Markdown parsing becomes fragile | Keep first slice simple: known files, bounded reads, controlled rendering. |
| Diagnosis questions need richer answers | Provide “observed diagnosis” and “limitations”; reserve hypotheses for explicit, labelled follow-up. |

## Open decisions for spec/design

1. Should deterministic rendering bypass LM Studio entirely for all harness-backed operational answers?
   - Recommended: yes for `event_list`, `availability_check`, and `availability_check_batch`.
2. Should manual be in one file or split?
   - User selected `docs/ai.md`; keep one file initially, link from `backend/ai/README.md` if budget allows.
3. Should provider-native tool calling be implemented now?
   - Recommended: no; document future adapter shape only.
4. Should follow-up trigger terms be parsed from markdown in this slice?
   - Recommended: no; document terms in markdown and enforce alignment with tests.

## Proposed next phase

Proceed to `spec` for explicit requirements and scenarios covering:

- markdown policies/templates;
- deterministic harness-backed responses;
- developer manual requirements;
- LM Studio runtime constraints;
- no invented tool execution or unsupported RCA claims.
