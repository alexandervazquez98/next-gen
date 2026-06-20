# Apply Progress: AI Chat Markdown Policies

## Status consumed

- Change: `ai-chat-markdown-policies`
- Artifact store: OpenSpec repo files
- Structured status: proposal/spec/design/tasks present; apply was blocked until delivery strategy decision because 400-line budget risk was high.
- Delivery decision consumed: user approved chained/sliced delivery; Slice A only applied.
- Action context: repo-local, workspace `/home/alex/dev/next-gen/next-gen`, allowed edit root `/home/alex/dev/next-gen/next-gen`, no warnings.
- Strict TDD: active from `openspec/config.yaml`; support guidance read from `/home/alex/.pi/agent/gentle-ai/support/strict-tdd.md`.

## Workload / PR boundary

Slice A implemented only:

- Runtime markdown policies/templates.
- Deterministic loader/renderer for operational harnesses.
- Focused backend tests.

Slice B intentionally not implemented:

- `docs/ai.md` was not created.
- README links were not updated for this slice.

No deployment was performed.

## Completed tasks and persisted checkbox evidence

Persisted tasks updated in `openspec/changes/ai-chat-markdown-policies/tasks.md` for completed Slice A items:

- Pre-apply delivery guard confirmed as chained/sliced delivery.
- No-deploy guard observed.
- Policy/template artifact tests added.
- Markdown policy/template files created.
- Deterministic renderer and unsupported-claim tests added.
- Known-path bounded markdown loader added.
- `DETERMINISTIC_HARNESS_TYPES` and `render_harness_response()` added.
- Deterministic rendering implemented for `event_list`, `availability_check`, and `availability_check_batch`.
- `complete_chat()` now bypasses LM Studio for operational harnesses and uses `deterministic-template` model label.
- Non-harness and unknown-harness LM Studio paths preserved.
- Focused backend tests run and passing.
- Slice A rollback boundary documented/checked.

## Files changed by Slice A

- `backend/ai/policies/response-boundaries.md`
- `backend/ai/policies/lmstudio-runtime.md`
- `backend/ai/policies/followup-intents.md`
- `backend/ai/templates/event_list.md`
- `backend/ai/templates/availability_check.md`
- `backend/ai/templates/availability_check_batch.md`
- `backend/services/ai_chat_service.py`
- `backend/tests/test_ai_chat_service.py`
- `openspec/changes/ai-chat-markdown-policies/tasks.md`
- `openspec/changes/ai-chat-markdown-policies/apply-progress.md`

Note: the working tree already contains earlier AI chat changes outside this Slice A boundary. This progress report describes only work performed for Slice A.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| Policy/template artifacts | `backend/tests/test_ai_chat_service.py` | Unit/file contract | ✅ 33/33 via venv | ✅ 8 failing tests included missing files/functions | ✅ 42/42 after markdown/code | ✅ policy, runtime, follow-up, 3 templates | ✅ bounded loader separated from renderer |
| Deterministic event list renderer | `backend/tests/test_ai_chat_service.py` | Unit | ✅ 33/33 via venv | ✅ event-list facts/empty/unsafe-claim tests failed | ✅ event-list render passed | ✅ non-empty Spanish + empty English | ✅ symptom helper extracted |
| Deterministic availability renderers | `backend/tests/test_ai_chat_service.py` | Unit | ✅ 33/33 via venv | ✅ single/batch/failure tests failed | ✅ availability renderers passed | ✅ reachable, unreachable, ci_not_found, batch | ✅ shared formatting helpers added |
| LM Studio bypass/preservation | `backend/tests/test_ai_chat_service.py` | Unit | ✅ 33/33 via venv | ✅ bypass test failed due LM call | ✅ bypass returns `deterministic-template` | ✅ no-harness and unknown-harness still call model | ✅ deterministic branch isolated in `complete_chat()` |

## Test commands run

- `cd backend && python -m pytest backend/tests/test_ai_chat_service.py` → failed in this environment because system Python has no `pytest` module.
- `backend/.venv/bin/python -m pytest backend/tests/test_ai_chat_service.py` → baseline before edits: 33 passed, 1 warning.
- `backend/.venv/bin/python -m pytest backend/tests/test_ai_chat_service.py -q` after RED → 8 failed, 34 passed, 1 warning.
- `backend/.venv/bin/python -m pytest backend/tests/test_ai_chat_service.py -q` after GREEN iterations → 42 passed, 1 warning.
- `cd backend && PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_ai_chat_service.py` → 42 passed, 1 warning.
- `python -m py_compile backend/services/ai_chat_service.py backend/routers/ai.py backend/tests/test_ai_chat_service.py` → passed.
- `git diff --check` → passed.
- `test ! -f docs/ai.md` → passed.

## Deviations from design

- Markdown files are loaded as auditable contracts and safe known-path text, but their contents are not parsed as a DSL.
- Existing fallback helper names remain for compatibility, now delegating deterministic operational harnesses to the new renderer.
- The configured exact command `cd backend && python -m pytest backend/tests/test_ai_chat_service.py` cannot run in this shell because system Python lacks `pytest`; the project venv command and PATH-adjusted command passed.

## Remaining tasks

Slice B and broad validation remain unchecked:

```text
- [ ] Add a lightweight doc test or checklist-style validation, if existing project conventions support it, that `docs/ai.md` exists and mentions required paths and boundaries. If no doc tests exist, record manual review evidence during verify.
- [ ] Create `docs/ai.md` covering LM Studio connection/env vars, OpenAI-compatible `/v1/chat/completions`, model/timeout/max-token/context-length tuning, and reasoning-model empty-content behavior.
- [ ] Document identity files: `backend/ai/identity/Soul.md`, `backend/ai/identity/scope.md`, `backend/ai/identity/context-policy.md`, and `backend/ai/identity/session-bootstrap.md`, including that identity grants no execution/write authority.
- [ ] Document backend-owned harness lifecycle: intent inference, permission gates, target resolution, harness execution, harness-result injection or deterministic rendering, persistence, and follow-up resolution.
- [ ] Document provider-native toolcalling as a future adapter path, not the primary path for this change.
- [ ] Document response policies/templates and where to edit them.
- [ ] Document Raven/write boundaries: model must not directly write to Raven, SQLite, Neo4j, Postgres, CMDB, or operational systems.
- [ ] Optionally add a short link from `backend/ai/README.md` to policies, templates, and `docs/ai.md` if it does not push the slice over budget.
- [ ] Install backend test dependencies if needed: `cd backend && python -m pip install -r requirements.txt -r requirements-dev.txt`
- [ ] Run full backend tests before review: `cd backend && python -m pytest`
- [ ] Slice B rollback: revert `docs/ai.md` and optional README link only; no runtime behavior should be affected.
```

## Risks

- Repository working tree includes pre-existing AI chat/frontend/config changes from earlier work; Slice A did not attempt to isolate or revert them.
- Full backend test suite was not run in apply; focused AI chat tests passed.
- Independent review is still required by parent gate.
