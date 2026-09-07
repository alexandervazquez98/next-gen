# Proposal: LM Studio HTTP Error Mapping (#460)

## Intent

When LM Studio returns HTTP 400/404/500, `_post_lm_studio_chat_completion` raises `LMStudioError("LM Studio is unavailable")` and `routers/ai.py` surfaces it as **HTTP 502** — indistinguishable from a connection refusal. Operators cannot tell "model not found" from "LM Studio down". Fix: split the `HTTPError` branch, capture upstream status/reason, surface it in the 502 detail.

## Scope

### In Scope
- Add `LMStudioRequestRejected(LMStudioError)` with `status: int`, `body_preview: str`.
- Split `except URLError` → `except HTTPError` (first) + `except URLError` (second).
- Read up to **512 bytes** of `exc.read()` when `exc.fp` is present.
- New `except LMStudioRequestRejected` arm in `routers/ai.py`: 502 with detail `"LM Studio rejected the request (status=<code>): <body or reason>"`.
- Tests: HTTPError 400/404/500 at service + route; preserve existing 504 / 502-network tests.

### Out of Scope
- 4xx vs 5xx split at HTTP layer (issue accepts both as 502).
- Replacing `urlopen` with `httpx`/`requests`.
- Upstream payload redaction.

## Capabilities

### New Capabilities
- `lm-studio-error-mapping`: HTTP error classification for LM Studio. Separates upstream HTTP rejections from connection failures; surfaces upstream status/reason.

### Modified Capabilities
- None.

## Approach

1. New exception `LMStudioRequestRejected(LMStudioError)` with `.status: int`, `.body_preview: str` (≤512 bytes).
2. Split `except URLError` into `except HTTPError` (first — subclass) + `except URLError`. `HTTPError` arm logs `exc.code`, reads `exc.fp` ≤512 bytes, raises `LMStudioRequestRejected`. Keep network/timeout and parse-failure arms.
3. In `routers/ai.py`, add `except LMStudioRequestRejected` before `except LMStudioError`; 502 with formatted detail; log upstream status at WARNING.
4. Tests for HTTP 400/404/500 → `LMStudioRequestRejected` and route tests asserting the new 502 detail.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/services/ai_chat_service.py` | Modified | New exception class; split `except` chain ~line 277. |
| `backend/routers/ai.py` | Modified | New `except LMStudioRequestRejected` arm ~line 574. |
| `backend/tests/test_ai_chat_service.py` | Modified | New HTTPError tests; existing 985/1003/2342 untouched. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Wrong handler order — `URLError` before `HTTPError` swallows branch | Low | Handler order pinned in spec; review checks. |
| `LMStudioError("LM Studio is unavailable")` test regression | Low | Message preserved for non-HTTP network failure. |
| Unbounded body leak in logs/detail | Low | Hard 512-byte cap; redaction deferred. |

## Rollback Plan

Revert the single PR. `LMStudioRequestRejected` is additive (sibling of `LMStudioError`); removing it restores current behavior.

## Dependencies

- None — stdlib `urllib.error.HTTPError` only.

## Success Criteria

- [ ] LM Studio 400/404/500 → 502 with detail containing upstream status and reason/body.
- [ ] Connection refusal → 502 `"LM Studio is unavailable"` (existing test green).
- [ ] Timeout → 504 (existing test green).
- [ ] New tests cover 400/404/500 at service + route; all green.