# LM Studio Error Mapping Specification

## Purpose

The LM Studio HTTP integration MUST classify upstream errors so operators can distinguish "LM Studio rejected the request" from "LM Studio is unreachable" or "timed out". `HTTPError` MUST be detected before `URLError` so upstream status and a bounded body excerpt surface; non-HTTP network failures and timeouts MUST keep current messaging.

## Requirements

### Requirement: 4xx upstream HTTP errors surface rejection details

When `urlopen` raises HTTPError with a 400-499 status, the system MUST raise `LMStudioRequestRejected(LMStudioError)` carrying `status: int` and `body_preview: str`, reading at most **512 bytes** of `exc.read()` when `exc.fp` is present, and MUST log status and body preview at WARNING. `HTTPError` MUST be caught before `URLError`. The chat route MUST return **HTTP 502** with detail `"LM Studio rejected the request: <reason>"`, where `<reason>` is the body preview or `exc.reason` when no body is readable.



#### Scenario: 400 with JSON body yields rejection detail

- GIVEN LM Studio responds with `HTTPError(code=400, fp=<body '{"error":"unknown model"}'>)`
- WHEN the chat route handles it
- THEN the response MUST be HTTP 502 with detail containing `"LM Studio rejected the request:"` and the JSON.

#### Scenario: 404 with `exc.fp is None` falls back to `exc.reason`

- GIVEN LM Studio responds with `HTTPError(code=404, msg="Not Found", fp=None)`
- WHEN the chat route handles it
- THEN `body_preview` MUST equal `""`
- AND the detail MUST equal `"LM Studio rejected the request: Not Found"`.

#### Scenario: oversized body is truncated to 512 bytes

- GIVEN LM Studio responds with `HTTPError(code=400, fp=<body of 5000 bytes>)`
- WHEN the function reads it
- THEN `body_preview` MUST equal the first 512 bytes of the upstream body.

### Requirement: 5xx upstream HTTP errors surface upstream error details

When `urlopen` raises HTTPError with a 500-599 status, the system MUST raise `LMStudioRequestRejected` carrying `status: int` and `body_preview: str`. The chat route MUST return **HTTP 502** with detail `"LM Studio upstream error: <status> <reason>"`, where `<reason>` is the body preview or `exc.reason` when no body is readable.

#### Scenario: 500 with body yields upstream error detail

- GIVEN LM Studio responds with `HTTPError(code=500, fp=<body 'oops'>)`
- WHEN the chat route handles it
- THEN the response MUST equal HTTP 502 with detail `"LM Studio upstream error: 500 oops"`.

#### Scenario: 503 with empty body falls back to `exc.reason`

- GIVEN LM Studio responds with `HTTPError(code=503, msg="Service Unavailable", fp=None)`
- WHEN the chat route handles it
- THEN the detail MUST equal `"LM Studio upstream error: 503 Service Unavailable"`.

### Requirement: Non-HTTP network failures preserve "LM Studio is unavailable"

When `urlopen` raises a non-HTTPError `URLError`, the system MUST raise `LMStudioError("LM Studio is unavailable")` and the chat route MUST return **HTTP 502** with detail `"LM Studio is unavailable"`.

#### Scenario: connection refused stays as 502 unavailable

- GIVEN LM Studio is not listening on the configured port
- WHEN `urlopen` raises `URLError(reason=ConnectionRefusedError)`
- THEN the function MUST raise `LMStudioError("LM Studio is unavailable")`
- AND the route MUST respond HTTP 502 with detail `"LM Studio is unavailable"`.


#### Scenario: DNS failure is NOT a rejection

- GIVEN the configured `base_url` host does not resolve
- WHEN `urlopen` raises `URLError(reason=gaierror)`
- THEN the function MUST raise `LMStudioError("LM Studio is unavailable")`, NOT `LMStudioRequestRejected`.

### Requirement: Timeouts map to 504 Gateway Timeout

When `urlopen` raises builtin `TimeoutError`, or `URLError(reason=TimeoutError)`, the system MUST raise `LMStudioTimeoutError("LM Studio request timed out")` and the chat route MUST return **HTTP 504 Gateway Timeout** with detail `"LM Studio request timed out"`.

#### Scenario: direct timeout raises the timeout exception

- GIVEN LM Studio exceeds the configured timeout
- WHEN `urlopen` raises builtin `TimeoutError`
- THEN the function MUST raise `LMStudioTimeoutError`
- AND the route MUST respond HTTP 504 with detail `"LM Studio request timed out"`.


#### Scenario: URLError wrapping TimeoutError stays a timeout

- GIVEN `urlopen` raises `URLError(reason=TimeoutError("read timed out"))`
- WHEN the function processes the error
- THEN it MUST raise `LMStudioTimeoutError`, NOT `LMStudioRequestRejected` or `LMStudioError`.
