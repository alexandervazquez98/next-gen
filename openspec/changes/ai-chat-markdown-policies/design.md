# Design: AI Chat Markdown Policies and Deterministic Harness Responses

## Change

`ai-chat-markdown-policies`

## Executive summary

This design keeps the current backend-owned AI chat harness flow intact and moves its operator-facing rules into auditable markdown policy and template files. Operational harness responses for `event_list`, `availability_check`, and `availability_check_batch` will be rendered deterministically by backend code instead of being rewritten by LM Studio, preventing unsupported RCA, congestion, power, cabling, firewall, service-health, stable/optimal, resolved, or event-closure claims.

The implementation should be sliced if the developer manual pushes review size above the 400-line budget:

1. Slice A: policies/templates, minimal loader/renderer, routing decision, regression tests.
2. Slice B: `docs/ai.md` developer manual and optional README links.

No deployment should occur unless explicitly approved.

## Current implementation constraints to preserve

Current files inspected:

- `backend/services/ai_chat_service.py`
- `backend/routers/ai.py`
- `backend/ai/identity/*.md`
- `backend/ai/tools/*.md`
- `backend/tests/test_ai_chat_service.py`

Existing behavior to preserve:

- LM Studio uses OpenAI-compatible `/v1/chat/completions` via configured `LM_STUDIO_BASE_URL`.
- Backend owns chat history and replays bounded prior turns.
- Backend infers or validates `event_list`, `active_events`, `availability_check`, and `availability_check_batch` intents.
- Router permission gates run before harness execution.
- `event_list` status filters remain `OPEN`, `ACK`, `CLOSED`, `RECOVERED`, `ACTIVE`, `CONSOLE`.
- `event_list` severity filters remain `CRITICAL`, `WARNING`, `INFO`.
- Follow-up availability checks use the latest same-user `event_list` harness result and keep the batch cap at 5 CIs.
- Named-area follow-ups, e.g. `islas agrarias`, continue to filter recent event-list CIs through existing normalized-term matching.
- Disabled LM Studio still prevents harness side effects at the chat endpoint entrypoint.
- Empty-content fallback remains safe for harness-backed responses.

## Proposed file layout

```text
backend/ai/
  policies/
    response-boundaries.md
    lmstudio-runtime.md
    followup-intents.md
  templates/
    event_list.md
    availability_check.md
    availability_check_batch.md

docs/
  ai.md
```

Optional, if line budget allows:

```text
backend/ai/README.md          # short index linking identity, tools, policies, templates
```

## Markdown contracts

### `backend/ai/policies/response-boundaries.md`

Human-auditable policy. It should state:

- Operational facts come from backend context and harness evidence.
- The assistant must not claim a harness/tool ran unless `harness_result` exists.
- `reachable` means one current bounded ping responded.
- `unreachable` means one current bounded ping did not receive a response.
- Forbidden unsupported claims: root cause, congestion, power failure, cabling failure, firewall failure, service health, optimal state, stable state, resolved state, or event closure.
- Hypotheses are allowed only when explicitly labelled unconfirmed and backed by a separate evidence source.
- The model has no authority to write Raven, SQLite, Neo4j, Postgres, CMDB, or operational systems.

Runtime use in this slice: documentation plus optional bounded prompt snippet for non-deterministic chat. Tests validate the contract.

### `backend/ai/policies/lmstudio-runtime.md`

Developer/runtime policy. It should state:

- NEX-GEN uses LM Studio through OpenAI-compatible `/v1/chat/completions`.
- Native LM Studio stateful `/api/v1/chat` is not the default integration.
- Backend sends bounded history; provider state is not relied upon.
- Reasoning models may return `reasoning_content` while `message.content` is empty.
- `LM_STUDIO_MAX_TOKENS`, `LM_STUDIO_TIMEOUT_SECONDS`, and model context length trade off latency and completeness.
- Harness-backed deterministic rendering prevents operational answers from failing when model content is blank.

### `backend/ai/policies/followup-intents.md`

Policy documentation for current Python inference, not a runtime parser in this slice. It should document:

- Event-list concepts: events, eventos, alertas, incidentes, abiertos/open, activos, console/consola, recuperados/recovered, critical/críticos, warning, info.
- Availability follow-up concepts: estatus, estado, siguen/sigue, disponibilidad, chequeo/checa, verifica/verificar, revisa/revisar, funcionando, reachable/working/availability.
- Named-area matching against latest same-user `event_list` fields: `ci_name`, `ci_id`, `ci_hostname`, `ci_location_name`, `message`.
- Stopwords already embedded in `latest_event_list_ci_refs`, including operational filler such as `dame`, `actual`, `sitio`, `disponibilidad`, `chequeo`, `verifica`, `revisa`, `equipos`, `funcionando`, `como`.
- Availability batch cap of 5 CIs.

### Template files

Templates are reviewed response contracts, not a general markdown DSL. They should use plain markdown sections and a small fixed placeholder vocabulary documented in comments or a top section.

#### `backend/ai/templates/event_list.md`

Required response structure:

- Heading or first line with count and filters.
- `Eventos observados` / `Observed events` rows containing severity, status, CI, message, and last_seen when present.
- `Diagnóstico observado` limited to symptoms evidenced by event data:
  - latency/threshold breach if message/metric indicates latency or threshold;
  - availability/ping-check symptoms if event text or metric indicates ping/check/down;
  - recovered/open/ack/closed state as status only.
- `Límites` / `Limitations` stating event-list data alone does not confirm RCA or resolution.
- `Siguiente chequeo sugerido` with suggestions, not claims.
- Truncation notice when `truncated` is true.

#### `backend/ai/templates/availability_check.md`

Required response structure:

- CI identity/ref.
- Status, target when available, latency when available, detail when available.
- Interpretation limited to a current bounded ping.
- Limitations: ping reachability does not prove full service health, RCA, or event closure.

#### `backend/ai/templates/availability_check_batch.md`

Required response structure:

- Count of checks executed.
- One row per result with CI/ref, status, target, latency, detail.
- Interpretation limited to current bounded ping results.
- Limitations matching the single-check template.
- Preserve the existing cap of 5 results.

## Minimal loader/renderer approach

Avoid a fragile markdown DSL. Use known-path loading and deterministic Python formatting.

### Loader

Add a small helper in `backend/services/ai_chat_service.py` or a focused module such as `backend/services/ai_markdown.py` if it keeps the main service smaller:

- Known base dirs: `backend/ai/policies`, `backend/ai/templates`.
- Known file names only; no user-provided path input.
- Bounded reads, e.g. max 20 KB per file.
- UTF-8 text with `OSError` fallback.
- File content may be used for documentation/tests and optional prompt snippets.
- Missing template files must not break chat; renderer returns safe built-in deterministic output.

### Renderer

Recommended functions:

```python
DETERMINISTIC_HARNESS_TYPES = {"event_list", "availability_check", "availability_check_batch"}

def render_harness_response(query: str, harness_result: dict[str, Any]) -> str | None:
    ...
```

Implementation principles:

- Template selection is by exact `harness_result["type"]`.
- Use simple known-template rendering: deterministic code builds each section and may consult template text as the reviewed contract/header. Do not interpret arbitrary conditionals or loops from markdown.
- A minimal placeholder strategy is acceptable only for scalar header/footer values such as `{count}`, `{status}`, `{severity}`, `{ci_name}`. Lists should be rendered by Python to avoid inventing a markdown control language.
- Use existing `_prefers_spanish(query)` initially for Spanish vs English text. Keep it small; do not expand NLP scope unless tests require it.
- Reuse and expand existing fallback helpers rather than maintaining separate fallback and primary deterministic formats.
- Sanitize output by construction: only include harness fields already compacted by `_compact_event_summary` or ping metadata.
- When status is `ci_not_found`, `invalid_target`, or `error`, render the failure explicitly without implying a ping succeeded.

## `complete_chat` and endpoint decision flow

### Current flow

`chat_with_ai` currently:

1. Checks LM Studio enabled.
2. Infers or validates intent.
3. Enforces permissions.
4. Runs the harness.
5. Loads history.
6. Calls `complete_chat`, which always calls LM Studio when enabled.
7. Falls back only when model content is empty.
8. Persists response and `harness_result`.

### Proposed flow

Keep the endpoint shape and persistence contract, but let `complete_chat` choose deterministic rendering before LM Studio for operational harnesses.

```text
chat_with_ai
  check LM Studio enabled (unchanged for this slice)
  infer/validate intent (unchanged)
  permission gate (unchanged)
  maybe_run_harness (unchanged)
  load_chat_history (unchanged; can remain even if unused by deterministic path)
  complete_chat(query, context, harness_result, history)
    if harness_result.type in {event_list, availability_check, availability_check_batch}:
      response = render_harness_response(query, harness_result)
      if response:
        return {content: response, model: "deterministic-template" or current model label}
    else:
      call LM Studio
    if LM Studio content blank and harness_result exists:
      synthesize safe fallback
  save_chat_exchange (unchanged)
```

Decision details:

- Deterministic renderer bypasses LM Studio for the primary answer for the three operational harness types.
- Non-harness chat and future non-operational harnesses continue to call LM Studio.
- Existing `build_lm_studio_payload` no-harness warning remains required.
- Existing empty-content fallback remains as a safety net for any harness type not covered by deterministic rendering.
- To preserve current endpoint semantics, the router may continue requiring LM Studio to be enabled before any harness execution. A later change can decouple deterministic-only answers from LM Studio availability, but that is out of scope because current tests require disabled LM Studio to block harness side effects.
- Model label should be deterministic and non-misleading. Recommended: return `model` as configured LM Studio model only when LM Studio was called; return `"deterministic-template"` when bypassed. If frontend depends on a configured model string, document and test the chosen value.

## Data flow and contracts

```text
Client /api/ai/chat
  -> AIChatRequest validation
  -> infer_chat_intent / infer_followup_intent OR explicit intent
  -> permission gate in router
  -> maybe_run_harness
      event_list -> compact event summaries
      availability_check -> bounded ping metadata
      availability_check_batch -> max 5 child checks
  -> complete_chat
      deterministic renderer for operational harnesses
      LM Studio only for non-deterministic paths
  -> save_chat_exchange with assistant_response and harness_result
  -> AIChatResponse
```

No schema changes are required for request/response bodies.

## Developer manual design: `docs/ai.md`

The manual should be developer-facing and cover:

- LM Studio setup: env vars, base URL ending in `/v1`, chat-completions path, model name, timeout, max tokens, context length, reasoning-model empty-content behavior.
- Identity: `backend/ai/identity/Soul.md`, `scope.md`, `context-policy.md`, `session-bootstrap.md`; identity is bounded and does not grant tool/write authority.
- Toolcalling vs harnesses: provider-native tool calling is not the primary path; backend-owned harnesses validate permissions and execute tools.
- Harness lifecycle: intent inference, permission checks, target resolution, harness execution, result injection/rendering, persistence, follow-up resolution.
- Policies/templates: where to edit response boundaries, LM Studio runtime docs, follow-up intent policy, and deterministic response templates.
- Raven/write boundaries: model cannot write directly to Raven, SQLite, Neo4j, Postgres, CMDB, or operational systems; Raven bridges must remain backend/API controlled.
- Extension path: adding a new harness requires schema, permissions, executor, template/policy docs, tests, and only then optional provider-native adapter mapping.

## Tests

Primary test file: `backend/tests/test_ai_chat_service.py`. Add focused helpers to avoid broad line growth.

### Loader/template tests

- Policy/template files exist at expected paths.
- Template files contain required section names and required limitation language.
- Loader returns bounded text for known files and safe fallback for missing files.

### Deterministic rendering tests

- `event_list` deterministic response includes count, filters, CI names, severity/status, messages, and truncation notice when applicable.
- Empty `event_list` renders a no-events message with status/severity qualifiers.
- `availability_check` deterministic response includes CI, status, target, latency, and detail when present.
- `availability_check_batch` deterministic response includes each result up to the existing cap and bounded-ping interpretation.
- Failure statuses (`ci_not_found`, `invalid_target`, `error`) are reported without claiming reachability.

### LM Studio bypass/selection tests

- `complete_chat` with `event_list` does not call `_post_lm_studio_chat_completion` and returns deterministic content.
- Same for `availability_check` and `availability_check_batch`.
- `complete_chat` without harness still calls LM Studio and keeps the no-harness warning in the payload.
- Existing empty-content fallback still works for non-deterministic or unknown harness types.
- Update current `test_complete_chat_preserves_non_empty_model_response`: with an operational harness, non-empty model response should no longer be used because LM Studio is bypassed. Add a separate no-harness or unknown-harness test to preserve model-response behavior.

### Unsupported claim tests

Use a shared forbidden-fragment list such as:

```python
FORBIDDEN_UNSUPPORTED_CLAIMS = [
    "root cause", "causa raíz", "congestion", "congestión",
    "power", "energía", "cable", "cabling", "firewall",
    "service is healthy", "salud completa", "optimal", "óptimo",
    "stable", "estable", "resolved", "resuelto", "cerrado automáticamente",
]
```

Assertions should verify deterministic outputs do not contain these unsupported claims as affirmative conclusions. Limitation sections may mention forbidden concepts only as negated/non-confirmed statements, so tests should either:

- assert exact safe limitation phrases; and
- assert unsafe affirmative phrases are absent, e.g. `"root cause is"`, `"causa raíz es"`, `"power failure"`, `"congestion detected"`, `"is resolved"`.

Include event-list samples that could tempt overreach, e.g. latency threshold and ping-check down events, and assert output says only observed symptoms.

### Regression preservation tests

Keep existing coverage for:

- status/severity inference;
- `active_events` alias;
- unrecovered event inference;
- named-area follow-up filtering;
- availability batch cap;
- permission gates before harness execution;
- disabled LM Studio blocking harness side effects;
- no-harness warning in payload;
- bounded ping command and unsafe target rejection.

## Migration and rollback

Migration:

- Add markdown files without changing runtime behavior first if slicing is needed.
- Introduce renderer behind exact harness-type checks.
- Keep old fallback helpers until deterministic rendering is proven and tests are updated.
- No database migration is required.
- Persisted chat history remains compatible; only future `assistant_response` text format changes.

Rollback:

- Disable deterministic rendering by removing the exact harness-type branch or gating it behind a constant/env flag during implementation.
- Existing LM Studio path and fallback helpers can continue to serve responses.
- Markdown files are additive and can remain even if runtime rendering is rolled back.

Deployment:

- Do not deploy to `.22` or any environment during implementation unless explicitly approved.
- Run backend tests before requesting review.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Manual plus templates exceed 400-line review budget | Split into Slice A runtime/policies/templates/tests and Slice B manual/README links. |
| Markdown becomes stale relative to code | Tests assert required template/policy language and deterministic output semantics. |
| Renderer becomes a brittle DSL | Use known templates plus Python-rendered sections; avoid loops/conditionals in markdown. |
| Deterministic output feels less conversational | Use concise bilingual operator-friendly sections and preserve suggested next checks. |
| Forbidden-word tests conflict with limitation text | Test unsafe affirmative claims, and separately assert exact negated limitation phrases. |
| Bypassing LM Studio changes `model` response field | Choose and test an explicit deterministic label, or document why configured model remains. |

## Recommended implementation slices

### Slice A: policy/templates and runtime safety

Files likely touched:

- `backend/ai/policies/*.md`
- `backend/ai/templates/*.md`
- `backend/services/ai_chat_service.py`
- `backend/tests/test_ai_chat_service.py`

Goals:

- Add markdown policy/template artifacts.
- Add minimal loader and deterministic renderer.
- Bypass LM Studio for `event_list`, `availability_check`, `availability_check_batch` primary answers.
- Add unsupported-claim and regression tests.

### Slice B: developer manual

Files likely touched:

- `docs/ai.md`
- optional `backend/ai/README.md`

Goals:

- Document LM Studio, identity, harness lifecycle, provider-native toolcalling boundaries, policies/templates, Raven/write boundaries, and extension guidance.

If Slice A implementation stays under the review budget, Slice B may be combined; otherwise split.
