# Apply Progress: fix-460-lm-studio-http-error-mapping

## Status

All four TDD phases completed. Apply finished successfully on the first batch.

## Files Changed

| File | Lines added | Lines removed | Net |
|------|-------------|---------------|-----|
| `backend/services/ai_chat_service.py` | 49 | 0 | +49 |
| `backend/routers/ai.py` | 19 | 0 | +19 |
| `backend/tests/test_ai_chat_service.py` | 263 | 1 | +262 |
| **Total** | **331** | **1** | **+330** |

Well under the 400-line review budget.

## Phase Results

### Phase 1 — RED (failing tests written first)

8 task items (1.1–1.8) plus 3 regression guards written. Confirmed RED:
- 10 LMStudioRequestRejected assertions FAILED with `ImportError: cannot import name 'LMStudioRequestRejected'` — class didn't exist yet.
- 3 regression guards (timeout-via-URLError, plain-LMStudioError, connection refused) PASSED because they exercise pre-existing behavior that must stay intact.

Tests added at the end of `backend/tests/test_ai_chat_service.py`:
- `test_post_lm_studio_http_error_maps_to_request_rejected` — parametrized over HTTP 400/404/500/503 with body / `fp=None`.
- `test_post_lm_studio_http_error_truncates_body_to_512_bytes` — verifies the 512-byte cap.
- `test_post_lm_studio_connection_refused_keeps_unavailable_error` — plain URLError stays `LMStudioError("LM Studio is unavailable")`.
- `test_post_lm_studio_dns_failure_keeps_unavailable_error` — DNS `gaierror` is NOT a rejection.
- `test_post_lm_studio_url_error_wrapping_timeout_stays_timeout` — `URLError(reason=TimeoutError)` stays a timeout.
- `test_ai_chat_maps_request_rejected_to_502_with_detail` — parametrized over the 4 HTTP cases asserting route-level 502 + structured detail.
- `test_ai_chat_plain_lm_studio_error_still_unavailable` — regression guard.
- `test_ai_chat_timeout_still_504` — regression guard.

### Phase 2 — GREEN (minimal implementation)

3 task items (2.1–2.3) implemented:
- Added `LMStudioRequestRejected(LMStudioError)` in `backend/services/ai_chat_service.py` after `LMStudioTimeoutError`, carrying `status: int`, `body_preview: str`, `reason: str`. Constant `_BODY_PREVIEW_MAX_BYTES = 512`.
- Split `except urllib.error.URLError` chain in `_post_lm_studio_chat_completion` into:
  1. `except urllib.error.HTTPError as exc` FIRST — reads `exc.read()` when `exc.fp is not None`, bounded to 512 bytes; logs WARNING with `exc.code` and body preview; raises `LMStudioRequestRejected`.
  2. `except urllib.error.URLError as exc` AFTER — existing timeout-detection + `LMStudioError("LM Studio is unavailable")` preserved unchanged.
- Added `import logging` + `logger = logging.getLogger(__name__)` in `backend/routers/ai.py`.
- Added `except LMStudioRequestRejected as exc` BEFORE `except LMStudioError` in the chat route. 4xx → `"LM Studio rejected the request: <reason>"`; 5xx → `"LM Studio upstream error: <exc.status> <reason>"`. Logs WARNING, raises 502 HTTPException.
- Imported `LMStudioRequestRejected` in `backend/routers/ai.py`.

All 13 new tests flipped from RED → GREEN after the implementation.

### Phase 3 — REFACTOR

Body-preview read is only used in one place (HTTPError branch), so no helper extraction needed. The 512-byte cap is enforced exactly once via `_BODY_PREVIEW_MAX_BYTES`. No unused imports. No dead branches. Code stays minimal and localized per the change scope.

### Phase 4 — Final verification

- `python3.11 -m pytest tests/test_ai_chat_service.py` — **105 passed, 0 failed**.
- Targeted regression checks at lines 985, 1003, 2322, 2342 — all green (`test_ai_chat_maps_lm_studio_timeout`, `test_ai_chat_maps_lm_studio_error_without_traceback`, `test_post_lm_studio_logs_timeout_exception`, `test_post_lm_studio_logs_url_error`).
- `python3.11 -m pytest tests/` — **1992 passed, 6 pre-existing failures** in `test_auth_router_refresh.py::TestCookieDomainAndSecure` (2) and `test_writer_advisory_lock.py` (4). Confirmed pre-existing on base branch by `git stash` + re-run — these failures are unrelated to issue #460 and existed before any change.

## Spec ↔ Implementation mapping

| Spec requirement | Implementation site | Test |
|------------------|---------------------|------|
| 4xx → `LMStudioRequestRejected(status, body_preview)` | `services/ai_chat_service.py:127-146` class + `:302-325` HTTPError branch | `test_post_lm_studio_http_error_maps_to_request_rejected[400/404]` |
| 5xx → `LMStudioRequestRejected(status, body_preview)` | same branch | `test_post_lm_studio_http_error_maps_to_request_rejected[500/503]` |
| ≤512 bytes body cap | `services/ai_chat_service.py:149` constant + `:307` slice | `test_post_lm_studio_http_error_truncates_body_to_512_bytes` |
| `exc.fp is None` → body_preview="" + reason fallback | `:303-311` (fp guard) + `:312` reason capture | `test_post_lm_studio_http_error_maps_to_request_rejected[404/503]` |
| `HTTPError` caught BEFORE `URLError` | `:302` before `:326` | All 4 service-level HTTP tests |
| Plain URLError keeps "LM Studio is unavailable" | `:330-331` | `test_post_lm_studio_connection_refused_keeps_unavailable_error` + `:dns_failure_keeps_unavailable_error` |
| Timeout detection still first | `:299-301` (direct) + `:327-329` (URLError-wrapped) | `test_post_lm_studio_url_error_wrapping_timeout_stays_timeout` |
| 4xx → 502 "LM Studio rejected the request: <reason>" | `routers/ai.py:583-597` | `test_ai_chat_maps_request_rejected_to_502_with_detail[400/404]` |
| 5xx → 502 "LM Studio upstream error: <status> <reason>" | `routers/ai.py:585-588` | `test_ai_chat_maps_request_rejected_to_502_with_detail[500/503]` |
| Log status + body preview at WARNING | `services/ai_chat_service.py:313-318` + `routers/ai.py:589-593` | All tests (visible via caplog) |

## Constraints Honored

- Files changed are within the change scope: `services/ai_chat_service.py`, `routers/ai.py`, `tests/test_ai_chat_service.py`.
- No git history amendments; new commits only (commits will be created in a follow-up phase if requested).
- No push, no PRs, no destructive git operations.
- Generated artifacts default to English (test docstrings, comments, log messages).
- TDD mode strict-RED-GREEN-REFACTOR followed: tests written first, confirmed RED, then minimal implementation flipped them GREEN.

## Handoff

- Apply complete. Ready for `sdd-verify`.
- The next phase should run the verification harness (acceptance scenarios, edge cases) and produce `verify-report.md`.
