# Tasks: LM Studio HTTP Error Mapping (#460)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~110 (30 LOC code + 80 LOC tests) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Split HTTPError/URLError, add `LMStudioRequestRejected`, router arms | PR 1 | `python3.11 -m pytest backend/tests/test_ai_chat_service.py -k "post_lm_studio or lm_studio_maps"` | Curl `/api/ai/chat` with LM Studio on/off | Revert PR restores `except URLError` chain |

## Phase 1: RED Tests (write all failing tests first)

- [x] 1.1 RED: HTTP 400 with JSON body — assert raises `LMStudioRequestRejected(status=400, body_preview='{"error":"unknown model"}')`; route → 502 with `"LM Studio rejected the request:"` + JSON. Patch `urlopen` with `HTTPError(url, 400, "Bad Request", hdrs, fp=BytesIO(b'{"error":"unknown model"}'))`.
- [x] 1.2 RED: HTTP 404 with `fp=None` — assert `body_preview == ""`; route detail equals `"LM Studio rejected the request: Not Found"`.
- [x] 1.3 RED: HTTP 500 with body `b'oops'` — assert `LMStudioRequestRejected(status=500, body_preview='oops')`; route detail equals `"LM Studio upstream error: 500 oops"`.
- [x] 1.4 RED: HTTP 503 with `fp=None`, `msg="Service Unavailable"` — route detail equals `"LM Studio upstream error: 503 Service Unavailable"`.
- [x] 1.5 RED: connection refused (`URLError(reason=ConnectionRefusedError)`) — assert `LMStudioError("LM Studio is unavailable")`, NOT rejection; route → 502 same detail.
- [x] 1.6 RED: DNS failure (`URLError(reason=gaierror)`) — assert `LMStudioError("LM Studio is unavailable")`; NOT `LMStudioRequestRejected`.
- [x] 1.7 RED: timeout via `URLError(reason=TimeoutError)` — assert `LMStudioTimeoutError`; route → 504 `"LM Studio request timed out"`.
- [x] 1.8 RED: HTTPError with 5000-byte body — assert `body_preview == first 512 bytes` only.

## Phase 2: GREEN Implementation

- [x] 2.1 Add `LMStudioRequestRejected(LMStudioError)` after line 124 in `backend/services/ai_chat_service.py` storing `self.status: int`, `self.body_preview: str`.
- [x] 2.2 In `_post_lm_studio_chat_completion`, split `except URLError` (line 277) into `except HTTPError` FIRST — log WARNING with `exc.code` + first 512 bytes of `exc.read()` when `exc.fp` is not None, raise `LMStudioRequestRejected`; keep `except URLError` AFTER unchanged.
- [x] 2.3 In `backend/routers/ai.py` before `except LMStudioError` (line 579), add `except LMStudioRequestRejected as exc`: 502 with `"LM Studio rejected the request: {reason}"` when `exc.status < 500`, else `"LM Studio upstream error: {exc.status} {reason}"`; log WARNING.

## Phase 3: REFACTOR

- [x] 3.1 Extract body-preview read to helper if duplicated; enforce 512-byte cap once.
- [x] 3.2 Remove unused imports / dead branches from the split.

## Phase 4: Final Verification

- [x] 4.1 Run `python3.11 -m pytest backend/tests/test_ai_chat_service.py` from `backend/` — full file green.
- [x] 4.2 Confirm existing tests at lines 985, 1003, 1018, 2342, 2359 stay green unchanged.
- [x] 4.3 Run `python3.11 -m pytest backend/tests/` — no adjacent regressions.