# Explore: AI Chat Markdown Policies and Deterministic Harness Responses

## Change

`ai-chat-markdown-policies`

## Goal

Move NEX-GEN AI chat behavior, response boundaries, follow-up intent policy, and deterministic harness response formats into auditable markdown artifacts while preserving the working flow already implemented for LM Studio and backend-owned harnesses.

## Current behavior observed

The AI chat flow currently works through a provider-neutral backend harness pattern:

1. Client sends `/api/ai/chat` with a user query and optional intent/context.
2. Backend infers or validates an intent.
3. Backend checks permissions.
4. Backend executes allow-listed harnesses such as `event_list`, `availability_check`, or `availability_check_batch`.
5. Backend appends a `Harness result` JSON block to the OpenAI-compatible `/v1/chat/completions` request.
6. LM Studio generates assistant text.
7. Backend stores `AIChatMessage` with `harness_result` for follow-up resolution.

Working features to preserve:

- `event_list` status filters: `OPEN`, `ACK`, `CLOSED`, `RECOVERED`, `ACTIVE`, `CONSOLE`.
- `event_list` severity filters: `CRITICAL`, `WARNING`, `INFO`.
- Bounded Neo4j query with `LIMIT limit + 1`.
- Per-user chat history replay into `/v1/chat/completions`.
- Follow-up availability checks using latest same-user `event_list` harness metadata.
- Named-area filtering such as `islas agrarias` resolving only matching CI refs.
- `availability_check_batch` capped to 5 CIs.
- No direct model writes to Raven/SQLite/CMDB.
- Backend permission enforcement before harness execution.
- Fallback response synthesis when LM Studio returns empty `content`.

## Current hardcoded policy and format locations

Hardcoded in `backend/services/ai_chat_service.py`:

- Prompt source lists: `REQUIRED_PROMPT_SOURCE_FILES`, `OPTIONAL_PROMPT_SOURCE_FILES`.
- System prompt char budget: `MAX_SYSTEM_PROMPT_CHARS`.
- No-harness warning appended to user content.
- Safe ping target rules.
- Compact event summary allowlist.
- Availability batch cap.
- Follow-up query normalization and stopwords.
- Deterministic fallback response wording for:
  - `event_list`
  - `availability_check`
  - `availability_check_batch`
- Spanish detection heuristic.
- Event severity sort order.

Hardcoded in `backend/routers/ai.py`:

- Pydantic schemas for backend-owned intents.
- Permission gates for diagnostics and event visibility.
- Regex intent inference for event list status/severity.
- Regex follow-up availability trigger detection.

Already in markdown under `backend/ai/`:

- Identity and scope:
  - `backend/ai/identity/Soul.md`
  - `backend/ai/identity/scope.md`
  - `backend/ai/identity/context-policy.md`
  - `backend/ai/identity/session-bootstrap.md`
- Tool catalog:
  - `backend/ai/tools/README.md`
  - `backend/ai/tools/event-list.md`
  - `backend/ai/tools/availability_check.md`
  - `backend/ai/tools/network-basic.md`
  - `backend/ai/tools/visualization.md`

Gap: markdown currently describes tool availability, but not enough of the enforceable response policy, deterministic formatting, follow-up intent phrases, or “what not to claim” rules.

## LM Studio constraints from documentation and live behavior

Relevant LM Studio documentation/behavior:

- OpenAI-compatible chat endpoint: `POST /v1/chat/completions`.
- The caller sends chat `messages`; prompt templates are applied automatically for chat-tuned models.
- Inference parameters such as `temperature`, `max_tokens`, and `top_p` are supplied in the payload.
- LM Studio also has native stateful chats under `/api/v1/chat`, but this project intentionally prefers backend-managed history over provider-specific state.

Live behavior observed during this change:

- Reasoning-capable models can populate `message.reasoning_content` while returning `message.content: ""`.
- `finish_reason: "length"` can occur when `reasoning_content` consumes the whole `max_tokens` budget.
- Increasing context length helped prompt fit, but `max_tokens` and backend timeout still bound completion latency.
- Generic model output can over-interpret harness data, e.g. claiming congestion, power failure, or RCA without evidence.

Implication: for operational harness results, the backend should prefer deterministic or tightly templated responses over free-form model interpretation.

## Problem statement

The system is currently functional but too much operational behavior lives in Python code or free-form model output. This creates three risks:

1. **Auditability risk**: Operators cannot easily inspect the response contract without reading code.
2. **Drift risk**: Markdown tool docs and actual Python behavior can diverge.
3. **LLM overreach risk**: The model may transform symptoms into unsupported RCA claims.

## Recommended direction

Introduce markdown-backed policy and response template files, then make Python load and enforce them with a narrow renderer.

Proposed files:

```text
backend/ai/policies/
  response-boundaries.md
  lmstudio-runtime.md
  followup-intents.md

backend/ai/templates/
  event_list.md
  availability_check.md
  availability_check_batch.md
```

### `response-boundaries.md`

Purpose: global behavioral limits for operational answers.

Should define:

- The model/backend may report observed harness data.
- The answer must not claim a tool ran unless `harness_result` exists.
- `reachable` only means current bounded ping responded.
- `unreachable` only means one bounded ping did not get a response.
- Do not claim RCA, power failure, cable cut, congestion, firewall, “resolved”, “optimal”, or “stable” unless supporting harness data exists.
- Hypotheses must be labelled as unconfirmed.

### `lmstudio-runtime.md`

Purpose: document provider behavior and tuning.

Should define:

- `/v1/chat/completions` is stateless; backend owns history.
- Native LM Studio stateful chats are not the default integration path.
- Reasoning models may emit `reasoning_content` and blank `content`.
- Backend handles empty `content` with deterministic fallback when harness data exists.
- `LM_STUDIO_MAX_TOKENS`, `LM_STUDIO_TIMEOUT_SECONDS`, and context length trade off latency and completeness.

### `followup-intents.md`

Purpose: human-readable trigger policy for follow-up intent inference.

Should define:

- Event list triggers: `eventos`, `alertas`, `incidentes`, `abiertos`, `críticos`, `recuperados`, etc.
- Availability follow-up triggers: `estatus`, `estado`, `siguen`, `sigue`, `disponibilidad`, `chequeo`, `verifica`, `funcionando`, etc.
- Stopwords for named-area matching: `dame`, `actual`, `sitio`, etc.
- Named-area matching behavior, e.g. `islas agrarias` filters latest event-list CIs.

Important: initial implementation can treat this markdown as policy documentation plus tests. Later implementation can parse structured sections if needed.

### Template files

Purpose: deterministic response formats for harness-backed answers.

`event_list.md` should constrain responses to:

- Count and filters used.
- Rows with severity/status/CI/message/last_seen.
- “Observed diagnosis” limited to symptoms:
  - latency threshold breach
  - availability event from ping-check
  - recovered/open status
- “Limitations” stating no RCA is confirmed by event list alone.
- “Next check” suggestions, not claims.

`availability_check_batch.md` should constrain responses to:

- CI, status, target, latency, detail.
- Interpretation limited to current bounded ping.
- Explicit caveat that ping reachability does not confirm service health, event closure, or RCA.

`availability_check.md` mirrors the batch format for one CI.

## Implementation shape for later phases

Suggested phases after proposal/spec/design approval:

1. Add markdown policy/template files.
2. Add a small markdown loader with bounded reads and fallback defaults.
3. Add a minimal deterministic renderer for harness types.
4. Prefer deterministic renderer for `event_list`, `availability_check`, and `availability_check_batch` when a harness result exists.
5. Optionally include compact policy snippets in the LM Studio prompt, selected by active harness type.
6. Keep current Python schemas, permissions, harness execution, and history logic unchanged unless required by spec.
7. Add tests that assert forbidden unsupported language does not appear in deterministic outputs.

## Non-goals

- Do not switch to LM Studio native stateful `/api/v1/chat`.
- Do not use provider-native tool calling as the primary execution path.
- Do not allow the model to execute tools directly.
- Do not remove backend permission gates.
- Do not add model writes to Raven/SQLite/CMDB.
- Do not implement a general markdown DSL unless the spec justifies it.

## Risks

- Loading too many markdown files into every prompt can increase token use and worsen reasoning/timeout behavior.
- Over-parsing markdown can create fragile runtime behavior.
- Fully deterministic responses may feel less conversational if not formatted carefully.
- Moving regex trigger policy to markdown without strong validation can reduce reliability.

## Open questions for proposal/spec

1. Should deterministic renderer be mandatory for all harness results, or only for operational harnesses (`event_list`, availability checks)?
2. Should diagnosis requests still call the model after deterministic data output, or should the backend provide a strict “observed diagnosis only” section?
3. Should follow-up intent trigger phrases be parsed from markdown in this change, or documented in markdown and enforced by tests while Python remains the parser?
4. Should frontend show harness metadata/debug evidence to operators, e.g. “availability_check_batch executed”?

## Recommended next phase

Proceed to proposal with a first slice focused on:

- Add markdown policies/templates.
- Use deterministic template rendering for current harness results.
- Keep Python intent inference and permission gates intact.
- Add tests preventing unsupported RCA claims in harness-backed responses.
