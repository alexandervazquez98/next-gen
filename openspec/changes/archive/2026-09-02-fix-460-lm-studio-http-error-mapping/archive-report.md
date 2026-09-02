# Archive Report: fix-460-lm-studio-http-error-mapping

**Change**: `fix-460-lm-studio-http-error-mapping`
**Archived**: 2026-09-02
**Branch**: `fix/458-459-460-ai-chat-neo4j-cleanup`
**Commit**: `7d0047a34cf3f47a1471d1c31341278c6f74a774`
**Issue**: Closes #460

## Intent

When LM Studio returned HTTP 400/404/500, `_post_lm_studio_chat_completion`
(`backend/services/ai_chat_service.py`) raised `LMStudioError("LM Studio is
unavailable")` and `routers/ai.py` surfaced it as **HTTP 502** — indistinguishable
from a connection refusal. Operators could not tell "model not found" from "LM
Studio down". The fix splits the `HTTPError` branch from the `URLError` branch
so the upstream status code and a bounded body excerpt reach the operator.

## Scope

### In Scope

- New exception `LMStudioRequestRejected(LMStudioError)` carrying
  `status: int`, `body_preview: str`, `reason: str`.
- Split `except urllib.error.URLError` into `except HTTPError` (first) +
  `except URLError` (second).
- 512-byte body-preview cap (`_BODY_PREVIEW_MAX_BYTES`) to bound log / detail
  size.
- New `except LMStudioRequestRejected` arm in `routers/ai.py`: 4xx →
  `"LM Studio rejected the request: <reason>"`; 5xx →
  `"LM Studio upstream error: <status> <reason>"`.
- WARNING-level logging of upstream status and body preview at both the service
  and the route layer.
- 13 new tests covering HTTPError 400/404/500/503 at service + route level, the
  512-byte cap, plus three regression guards (timeout-via-URLError,
  plain-LMStudioError, connection refused).

### Out of Scope

- 4xx vs 5xx split at the HTTP layer (issue accepts both as 502 — the operator
  signal lives in the detail string and the log).
- Replacing `urlopen` with `httpx`/`requests`.
- Upstream payload redaction (flagged as a follow-up suggestion in
  `verify-report.md`).

## Outcome

**Verdict**: PASS (per `verify-report.md`, evidence revision
`sha256:f5c1b5a25a0989a1fd5867b0cae5186b987cdfd7be808e933663c53525828539`).

| Metric | Final Value | Source |
|--------|-------------|--------|
| Tasks complete | 16 / 16 | archived `tasks.md` |
| Spec requirements | 4 / 4 compliant | `verify-report.md` Spec Compliance Matrix |
| Spec scenarios | 9 / 9 compliant | `verify-report.md` Spec Compliance Matrix |
| Tests in `test_ai_chat_service.py` | 105 / 105 passing | Phase 4 final run on commit `7d0047a` |
| New tests added | 13 (8 functions; 4 × 2 parametrized + 1 512-byte cap + 3 regression guards) | `apply-progress.md` |
| Verify verdict | PASS (0 blockers, 0 critical, 0 warnings) | `verify-report.md` |
| Production diff | +330 / -1 lines (well under the 400-line review budget) | `apply-progress.md` |

## Files Changed

| File | Lines added | Lines removed | Net |
|------|-------------|---------------|-----|
| `backend/services/ai_chat_service.py` | 49 | 0 | +49 |
| `backend/routers/ai.py` | 19 | 0 | +19 |
| `backend/tests/test_ai_chat_service.py` | 263 | 1 | +262 |
| **Total production code** (`ai_chat_service.py` + `routers/ai.py`) | **68** | **0** | **+68** |
| **Total commit** | **331** | **1** | **+330** |

## Test Coverage

### New tests (13)

Service-level (`_post_lm_studio_chat_completion`):

- `test_post_lm_studio_http_error_maps_to_request_rejected` — parametrized over
  HTTP 400 / 404 / 500 / 503 with body or `fp=None`. Asserts
  `LMStudioRequestRejected.status`, `body_preview`, and `reason`.
- `test_post_lm_studio_http_error_truncates_body_to_512_bytes` — verifies the
  512-byte cap exactly.
- `test_post_lm_studio_connection_refused_keeps_unavailable_error` — plain
  `URLError` keeps `LMStudioError("LM Studio is unavailable")`, NOT the new
  sibling.
- `test_post_lm_studio_dns_failure_keeps_unavailable_error` — `URLError(reason
  =gaierror)` is NOT a rejection.
- `test_post_lm_studio_url_error_wrapping_timeout_stays_timeout` —
  `URLError(reason=TimeoutError)` stays `LMStudioTimeoutError`.

Route-level (FastAPI `TestClient`):

- `test_ai_chat_maps_request_rejected_to_502_with_detail` — parametrized over
  HTTP 400 / 404 / 500 / 503 asserting route → 502 with structured detail.
- `test_ai_chat_plain_lm_studio_error_still_unavailable` — regression guard.
- `test_ai_chat_timeout_still_504` — regression guard.

### Preserved tests

All four pre-existing tests in `backend/tests/test_ai_chat_service.py` that
exercised the old handler chain remain green (confirmed in `apply-progress.md`
Phase 4): `test_ai_chat_maps_lm_studio_timeout`, `test_ai_chat_maps_lm_studio_
error_without_traceback`, `test_post_lm_studio_logs_timeout_exception`,
`test_post_lm_studio_logs_url_error`.

### Final test run

```text
$ cd backend && python3.11 -m pytest tests/test_ai_chat_service.py
============================= 105 passed, 42 warnings in 2.55s ==============================
```

## Spec Sync

The baseline spec at `openspec/specs/lm-studio-error-mapping/spec.md` was
created during this change and already contains the merged content. The delta
spec at `openspec/changes/fix-460-lm-studio-http-error-mapping/specs/
lm-studio-error-mapping/spec.md` was verified to mirror the baseline 1-for-1:

- Side-by-side diff: 4 requirements / 9 scenarios identical in name and content.
- Main spec carries the formatted `Purpose` + `Requirements` header the
  OpenSpec convention expects (not a bare delta).
- No further merge action was required; this archive moves the change folder
  with the delta and baseline already aligned.

| Domain | Action | Details |
|--------|--------|---------|
| `lm-studio-error-mapping` | Verified already merged | 4 requirements added, 0 modified, 0 removed |

## Archive Contents

| Artifact | Path | Status |
|----------|------|--------|
| proposal.md | `openspec/changes/archive/2026-09-02-fix-460-lm-studio-http-error-mapping/proposal.md` | OK |
| exploration.md | `…/exploration.md` | OK |
| specs/lm-studio-error-mapping/spec.md | `…/specs/lm-studio-error-mapping/spec.md` | OK |
| tasks.md | `…/tasks.md` | 16 / 16 complete |
| apply-progress.md | `…/apply-progress.md` | OK |
| verify-report.md | `…/verify-report.md` | OK — PASS |
| archive-report.md | `…/archive-report.md` | OK (this file — additive) |

## Mechanical Archive Verification

| Check | Result |
|-------|--------|
| Source directory removed | yes |
| Archive directory exists | `openspec/changes/archive/2026-09-02-fix-460-lm-studio-http-error-mapping/` |
| `diff -r` snapshot vs archive | status 0, empty output (byte-identical) |
| Archived `tasks.md` unchecked count | 0 |
| Active changes directory free of `fix-460-…` | yes |
| Production code untouched | yes (no edits to `services/ai_chat_service.py`, `routers/ai.py`, or tests during archive) |

`diff -r` readback verbatim output (snapshot at
`$TMPDIR/sdd-archive.*/source` vs. `openspec/changes/archive/2026-09-02-fix-46
0-lm-studio-http-error-mapping/`):

```text
$ diff -r "$snapshot_root/source" "openspec/changes/archive/2026-09-02-fix-460-lm-studio-http-error-mapping"
(no output — empty diff, status 0)
```

The archive report itself is additive and was written after the readback, so
it is correctly excluded from the source/destination comparison.

## Rollback

Revert the single commit on the fix branch:

```bash
git revert 7d0047a34cf3f47a1471d1c31341278c6f74a774
```

`LMStudioRequestRejected` is an additive sibling of `LMStudioError`; removing
it and the new `except HTTPError` arm restores the original `except URLError`
chain and the misleading "LM Studio is unavailable" 502 for upstream 4xx/5xx.

## Issue Reference

Closes #460 — "LM Studio HTTP 400 surfaces as misleading 'LM Studio is
unavailable' 502". The fix classifies upstream HTTP rejections distinctly
from connection failures and timeouts, and surfaces the upstream status and a
512-byte body excerpt in the response detail and in WARNING-level logs.

## SDD Cycle Complete

The change has been fully planned, implemented, verified, and archived. The
SDD cycle for `fix-460-lm-studio-http-error-mapping` is closed. Ready for the
next change.
