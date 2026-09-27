# AI Agent Guide — NEX-GEN Platform

**Version**: 1.0
**Audience**: AI agents operating NEX-GEN via REST API
**Role detection**: JWT `role` claim starts with `AI_` (e.g., `AI_DIAGNOSTIC`, `AI_OPERATOR`)

---

## Who You Are

You are an AI agent. You authenticate via JWT with a role that starts with `AI_`.

| Your role | What you can do |
|-----------|----------------|
| `AI_DIAGNOSTIC` | Read everything, run diagnostics, acknowledge events, add comments, update limited CI metadata |
| `AI_OPERATOR` | Everything `AI_DIAGNOSTIC` does + close events normally |

**You CANNOT**: manage users, roles, backups, dictionaries, or perform forced event closes.

---

## Your Operations

### Events

| When you want to... | Endpoint | Notes |
|---------------------|----------|-------|
| List active events | `GET /api/events?status=ACTIVE` | Filter by status |
| Get event detail | `GET /api/events/{event_id}` | Includes business context |
| Run diagnostic | `POST /api/events/{event_id}/diagnose` | PING/SNMP check, 5 min cooldown on same CI |
| Acknowledge | `POST /api/events/{event_id}/ack` | Adds audit comment, 10 min cooldown |
| Add comment | `POST /api/events/{event_id}/comment` | Free-form |
| Close event | `POST /api/events/{event_id}/close` | Body: `{"cause": "...", "note": "..."}`. 15 min cooldown. NOT forced close. |

**CRITICAL events**: You cannot close a CRITICAL severity event. You must alert a human.

### CIs (Configuration Items)

| When you want to... | Endpoint | Notes |
|---------------------|----------|-------|
| List CIs | `GET /api/nodes` | Scoped to allowed locations; there is no per-CI list endpoint — filter client-side |
| View CI metrics | `GET /api/nodes/{node_id}/metrics` | One of the few per-CI endpoints that exist |
| View related events | `GET /api/events/related/{ci_id}` | Active events for a CI; NOT under `/api/nodes/{node_id}/events` |
| Update CI metadata | `PUT /api/nodes/{node_id}/metadata` | **Only these fields allowed**: |
| **Propose a new CI (HITL)** | `POST /api/cmdb/proposals` | See [docs/ai/cmdb-proposals.md](./ai/cmdb-proposals.md) for the manifest schema, error codes, and worked example. Requires `AI_PROPOSE_CI`. |

> **Correction (2026-09-26)**: Earlier versions of this guide listed `GET /api/nodes/{node_id}` and `GET /api/nodes/{node_id}/events` as read endpoints. Both return 405 / 404 against the live API — the router in `backend/routers/nodes.py` does not define them. To inspect a single CI, list `GET /api/nodes` and filter client-side; for events tied to a CI, use `GET /api/events/related/{ci_id}` (defined at `backend/routers/events.py:133`).

**Allowed metadata fields:**
```json
{ "status", "pollingInterval", "owner", "location_name", "metadata" }
```

**BLOCKED fields** (403 returned if you try to change):
```
id, label, type, brand, model, serialNumber, firmwareVersion, ip, snmp, location
```

### Dictionaries

- **You can**: List, view, preview (live SNMP poll)
- **You CANNOT**: Create, update, delete, apply, bulk upload, bulk confirm

### Topology (Links)

- **You can**: List, view relationships, view full graph
- **You CANNOT**: Create or delete links

---

## Session lifecycle

Authentication uses HTTP-only cookies. If an API request fails because the access token expired, the client should attempt `POST /api/auth/refresh` and then retry the original request once.

Refresh attempts are rate-limited. Repeated invalid refresh tokens return:

```http
429 Too Many Requests
Retry-After: <seconds>
```

When you receive `429` from `/api/auth/refresh`, stop retrying and wait for `Retry-After`. Do not loop refresh calls; repeated retries extend lockout pressure and may hide the real authentication failure.

## What Blocks You

### Cooldowns (per CI, not global)

| Operation | Wait after running |
|-----------|-------------------|
| Diagnostic | 5 minutes |
| Acknowledge | 10 minutes |
| Close event | 15 minutes |
| CI metadata update | 2 minutes |

If blocked, response includes:
```json
{ "detail": "...", "cooldown_remaining_seconds": 180 }
```

### Behavioral Guards

| Pattern | Blocks you if... |
|---------|-----------------|
| Close without diagnostic | >3 closes in 1 hour on CIs without running diagnostic first |
| Ack flood | >20 acks in 10 minutes without any diagnostic run |
| Metadata stampede | >5 CI updates in 5 minutes |
| Bulk request | Trying to operate on >10 CIs at once |
| Same op concentration | >50 of same operation type per hour |

**If blocked**: Fix the pattern (run a diagnostic first, wait, etc.) before retrying.

### CRITICAL Events

You cannot close events with severity `CRITICAL`. Alert a human operator instead.

---

## Audit

Every operation you perform is logged. Logging includes: timestamp, your role, operation, target, result, and any blocked reason.

---

## Quick Reference: Allowed vs Blocked

### Fully blocked (any AI role)

```
DELETE /api/nodes/{node_id}           → 403
POST /api/nodes/upload                 → 403
PUT /api/dictionaries/{id}             → 403
DELETE /api/dictionaries/{id}           → 403
POST /api/links/**                     → 403 (create/delete links)
PUT /api/cis/{ci_id}/dictionary-exclusions  → 403
DELETE /api/cis/{ci_id}/applied-dictionary  → 403
POST /api/categories/**                → 403
POST /api/owners/**                   → 403
POST /api/metrics/**                  → 403 (create/delete)
POST /api/backup/**                   → 403
GET/POST/PUT/DELETE /api/users/**     → 403
GET/POST/PUT/DELETE /api/roles/**     → 403
POST /api/events/prune                 → 403
```

### Field restrictions on CI update

```
PUT /api/nodes/{node_id}/metadata
Allowed:   status, pollingInterval, owner, location_name, metadata
Blocked:   id, label, type, brand, model, serialNumber, firmwareVersion, ip, snmp, location
```

---

## JWT Expected Claims

```json
{
  "sub": "your-agent-id",
  "role": "AI_DIAGNOSTIC",
  "type": "ai_agent",
  "exp": 1234567890
}
```

Your role must be `AI_DIAGNOSTIC` or `AI_OPERATOR`. Tokens without `type: "ai_agent"` are rejected.

---

## If You Get a 403

- **"AI agents cannot modify fields: [x]"** → You're trying to change a blocked field. Use allowed fields only.
- **"Operation blocked: cooldown active"** → Wait for the cooldown to expire.
- **"Too many X without diagnostic run"** → Run a diagnostic on that CI first.
- **"AI cannot operate on more than 10 entities"** → Reduce batch size.
- **"CRITICAL events require human approval"** → Alert a human, do not retry.

## Error Code Guidance

The platform returns standard HTTP status codes with machine-parseable bodies. Match the response to the action below — do not retry blindly.

| Status | Typical cause | Action |
|--------|---------------|--------|
| `401 Unauthorized` | Access token expired or missing | Call `POST /api/auth/refresh` **once**, then retry the original request. If refresh itself returns 401, your session is invalid — re-authenticate from scratch. |
| `403 Forbidden` | Role lacks the required permission, behavioral guard tripped, cooldown active, or critical-event attempt | Inspect the `detail` field. See [If You Get a 403](#if-you-get-a-403) below for the common messages. Do not retry without changing behavior. |
| `404 Not Found` | The `{ci_id}` / `{event_id}` does not exist or is outside your scope | Refresh your CI list (`GET /api/nodes`) and re-resolve the identifier. Do not invent IDs. |
| `405 Method Not Allowed` | You called an endpoint that does not exist for this resource | Check the endpoint table in this guide. Many fabricated endpoints (e.g. `GET /api/nodes/{node_id}`) return 405 — they are not implemented. |
| `413 Payload Too Large` | Bulk upload (`POST /api/nodes/upload`) file > 5 MB | Split the file, or use `POST /api/nodes` in batches. The 5 MB limit is enforced server-side. |
| `422 Unprocessable Entity` | Pydantic field validation failed (missing required field, wrong type, enum mismatch) | Read the response body — Pydantic errors include the field path and a link to `pydantic.dev` docs. Fix the payload; do not retry with the same body. |
| `429 Too Many Requests` | Rate limit or refresh-token lockout | Read the `Retry-After` header (seconds). Stop and wait. Repeated retries extend the lockout and hide the real failure. |

**Field-restriction error codes are explicit.** When a CI metadata update hits a blocked field, the server returns 403 with `detail: "AI agents cannot modify fields: [label, type, ...]"`. Treat the array as the authoritative whitelist-negation; do not probe with arbitrary fields.

