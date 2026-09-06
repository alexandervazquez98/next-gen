## Exploration: LM Studio HTTP error mapping (#460)

### Current State

`_post_lm_studio_chat_completion` in `backend/services/ai_chat_service.py:260-292` makes the only HTTP call to LM Studio. The handler chain currently is:

| Branch | Exception caught | Raised | Router maps to |
|---|---|---|---|
| `except TimeoutError` (line 274) | builtin `TimeoutError` from `urlopen` | `LMStudioTimeoutError("LM Studio request timed out")` | 504 Gateway Timeout (`routers/ai.py:574`) |
| `except urllib.error.URLError` (line 277) | `URLError` (parent of `HTTPError`) | `LMStudioTimeoutError` if `reason` is a `TimeoutError`, else **`LMStudioError("LM Studio is unavailable")`** | 502 Bad Gateway (`routers/ai.py:579-583`) |
| `except Exception` (line 283) | anything else from URL/JSON | `LMStudioError("LM Studio response could not be parsed")` | 502 Bad Gateway |

**Bug confirmed.** `urllib.error.HTTPError` is a subclass of `URLError` (Python stdlib). When LM Studio responds with `400 unknown model`, `404 not found`, or `500 upstream`, `urlopen` raises `HTTPError(url, code, msg, hdrs, fp)`. The current `except URLError` branch discards `exc.code`, `exc.reason`, and `exc.read()` and unconditionally raises `LMStudioError("LM Studio is unavailable")`. The router then surfaces a misleading 502 — the operator cannot distinguish "LM Studio returned an HTTP error" from "connection refused".

Test coverage at the `_post_lm_studio_chat_completion` unit level only exercises `urllib.error.URLError("Connection refused")` (a true network failure). There is **no existing test that simulates an `HTTPError`**, so the regression has been silent.

Class hierarchy (`ai_chat_service.py:119-124`) is minimal:

```
LMStudioError(Exception)
└── LMStudioTimeoutError(LMStudioError)
```

`LMStudioError` carries only the exception message; no `status` or `body` attribute.

### Affected Areas

- `backend/services/ai_chat_service.py:260-292` — `_post_lm_studio_chat_completion`. Bug site.
- `backend/services/ai_chat_service.py:119-124` — class hierarchy. May need a sibling `LMStudioRequestRejected` (or `LMStudioHTTPError`) carrying `status: int` and `body_preview: str`.
- `backend/routers/ai.py:574-583` — exception → HTTP mapping for `LMStudioError` / `LMStudioTimeoutError`. Will need a third branch for the new rejected class so the upstream status can be surfaced in the response detail.
- `backend/tests/test_ai_chat_service.py:985-1018` — existing tests `test_ai_chat_maps_lm_studio_timeout` and `test_ai_chat_maps_lm_studio_error_without_traceback` must continue to pass. The second asserts `detail == "LM Studio is unavailable"` for a plain `LMStudioError` — this message must be preserved for the **network-failure** sub-case of `LMStudioError` (i.e. the test's `LMStudioError("Connection refused: stack")` case).
- `backend/tests/test_ai_chat_service.py:2342-2360` — `test_post_lm_studio_logs_url_error` patches `urllib.request.urlopen` with a plain `URLError("Connection refused")`; asserts `LMStudioError, match="unavailable"`. Must stay valid.

### Downstream coupling

- `LMStudioError` is referenced **only** in `routers/ai.py:15,579` and `services/ai_chat_service.py:119, 282, 285, 291, 1103`. No other backend module imports it.
- `LMStudioTimeoutError` is referenced **only** in `routers/ai.py:16,574` and `services/ai_chat_service.py:123, 276, 280`. No other backend module imports it.
- No frontend service consumes these exceptions directly; the API just emits an HTTP error response.
- Adding a new sibling class is backward compatible: existing `except LMStudioError` arms (and the eventual `except LMStudioTimeoutError` arm, which must remain before it) keep matching as before.

### Approaches

1. **Split `except` chains + sibling exception class** (recommended by the issue body)
   - Keep `LMStudioTimeoutError` (504) and the bare `LMStudioError` fallback (502 "LM Studio is unavailable" for non-HTTP network errors and parse failures).
   - Add `LMStudioRequestRejected(LMStudioError)` carrying `status: int` and `body_preview: str`.
   - Replace `except URLError` with `except HTTPError` first (logs `code`, reads up to 512 bytes of body, raises the new class) then `except URLError` (existing network/timeout logic, kept).
   - In `routers/ai.py`, add an `except LMStudioRequestRejected` arm that maps to **502** with detail `"LM Studio rejected the request: <reason>"` and logs the upstream status. The HTTP code stays 502 — the **operator signal** is in the detail string and the log, matching the issue's "Expected Behavior". A 5xx upstream can stay on the same arm (502) since both reflect "LM Studio rejected/aborted the request"; the log already records `code`.
   - Pros: Smallest behavioral diff, preserves every existing assertion, no router rewrite needed beyond one new arm. Backward compatible for any external caller of these classes.
   - Cons: Same HTTP status (502) used for both LM Studio unreachable and LM Studio 4xx — operator must read the detail body to tell them apart. Matches the issue's spec exactly (which keeps 502 for 4xx).
   - Effort: **Low** (~30-40 LOC service + router + 5 small new tests).

2. **Alternative: two sibling classes (`LMStudioUpstreamClientError` + `LMStudioUpstreamServerError`) mapped to distinct codes**
   - 4xx → 502 with `"LM Studio rejected the request: <reason>"`; 5xx → 502 with `"LM Studio upstream error: <status> <reason>"` (per the issue's "Proposed Fix" expectation, both 502 — splitting further is gratuitous because the bug report collapses them).
   - Pros: Slightly better operator signal at HTTP level.
   - Cons: Distinction between upstream 4xx and 5xx is rarely actionable from the chat UI, doubles the class count, and broadens the change scope. The issue explicitly accepts both as 502.
   - Effort: **Low–Medium** (one extra class + one extra router arm).

3. **`isinstance(exc, HTTPError)` inside a single `except URLError`**
   - One handler branch with internal type discrimination.
   - Pros: Shortest code.
   - Cons: Re-raises `LMStudioError` (not a sibling), so the router cannot tell upstream 4xx from network failure; the detail has to embed status. Tests cannot easily check that the router emitted "rejected" vs "unavailable" because they share the exception class. **Does not address the operator's signal** — that's the whole point of the fix.
   - Effort: **Low** but does not actually fix the bug as specified.

### Recommendation

**Approach 1**: add `LMStudioRequestRejected(LMStudioError)` with `status: int` and `body_preview: str`, split the `except URLError` block into `except HTTPError` + `except URLError`, keep the bare `LMStudioError` for "parse error" / "disabled" / true network failure unchanged, and add one router arm in `routers/ai.py` for the new class. Matches the issue's "Proposed Fix" verbatim.

Specifics worth pinning in the proposal/spec:
- Reject branch detail format: `f"LM Studio rejected the request (status={exc.code}): {body_preview or exc.reason}"` truncated to a sane length.
- Body read is bounded to **512 bytes** (issue's proposed cut-off; prevents unbounded logging of large upstream payloads).
- Reading `exc.fp` is mandatory — `HTTPError` exposes `fp=None` when constructed manually, so guard with `if exc.fp`.
- Network branch in the new `except URLError` keeps the existing `isinstance(getattr(exc, "reason", None), TimeoutError)` defensive check (unchanged behavior).
- New tests at `_post_lm_studio_chat_completion` level for HTTP 400/404/500 (using `urllib.error.HTTPError(url, code, msg, hdrs, fp)`), and at the route level (TestClient) asserting a 502 whose detail contains the upstream status / reason. Existing tests at lines 985, 1003, 2342 must remain green untouched.

### Risks

- **Test message regression**: if the proposal inadvertently changes the message for the plain `LMStudioError("LM Studio is unavailable")` branch, `test_ai_chat_maps_lm_studio_error_without_traceback` (line 1018) and `test_post_lm_studio_logs_url_error` (line 2359) will fail. The recommended approach keeps the literal string intact for non-HTTP `LMStudioError`.
- **Body re-read safety**: `HTTPError.__init__` does not eagerly read `fp`. The handler must call `exc.read()` exactly once; downstream callers must not. Since the new exception captures `body_preview` as a string, downstream consumers see only the slice.
- **Body truncation semantics**: 512-byte preview may leak sensitive content from LM Studio's error response into logs and the 502 detail. Out of scope for this fix (the current code already logs message strings at ERROR level), but worth flagging in the design phase.
- **HTTPError subclass ordering**: `HTTPError` MUST be caught before its parent `URLError` in the `try/except` chain. Python's `urllib.error.HTTPError` is `URLError` subclass, so handler order matters — easy to get wrong in review.
- **Review budget**: change is <100 LOC total across `ai_chat_service.py` + `routers/ai.py` + tests. Comfortably under the 400-line budget. No need for chained PRs.

### Ready for Proposal

**Yes.** Scope is narrow, root cause is verified, the proposed fix aligns with the issue's verbatim recommendation, existing tests pin the regression surface, and no other module is affected. Proceed to `sdd-propose` with the following scoped items:

- Add `LMStudioRequestRejected` sibling class.
- Split `except URLError` into `except HTTPError` + `except URLError`.
- Add router arm in `routers/ai.py`.
- Add focused tests: `_post_lm_studio_chat_completion` returns `LMStudioRequestRejected` for HTTPError 400/404/500; route-level 502 detail includes upstream status/reason; existing 504 and 502-network tests pass unchanged.
