# CMDB AI Manifest Guide — feat-cmdb-ai-handoff

> **Audience**: External AI agents (the internal `AIAgentConsole`, the MCP
> wrapper, and any external HTTP client) that want to propose new
> Configuration Items (CIs) to the CMDB through the Human-In-The-Loop gate.

This guide is the contract. If a field, endpoint, or behavior is not documented
here, treat it as unsupported and ask before submitting.

---

## What you can do

| Action | Endpoint | Required permission |
|---|---|---|
| Submit a CI manifest | `POST /api/cmdb/proposals` | `AI_PROPOSE_CI` |
| List pending proposals | `GET /api/cmdb/proposals` | `CI_VIEW` |
| Read one proposal (manifest + audit) | `GET /api/cmdb/proposals/{id}` | `CI_VIEW` |
| Approve a DRAFT proposal (commits the `:CI`) | `POST /api/cmdb/proposals/{id}/approve` | `CI_APPROVE_PROPOSAL` |
| Revoke a DRAFT or APPROVED proposal | `POST /api/cmdb/proposals/{id}/revoke` | `CI_APPROVE_PROPOSAL` |

> **You cannot edit** a proposal after submission. Approve or revoke only.

---

## Manifest schema

```json
{
  "schema_version": 1,
  "ci": {
    "id":              "CI-N9X3K2",
    "label":           "Core Router Bogotá",
    "category":        "Router",
    "brand":           "Cisco",
    "model":           "ASR-1000",
    "serialNumber":    "FOC1234X5YZ",
    "firmwareVersion": "17.09.01a",
    "ip":              "10.20.30.1",
    "owner":           "NOC-LATAM",
    "location_name":   "Bogotá DC-1",
    "status":          "OK",
    "pollingInterval": 60,
    "metadata":        { "rack": "R12", "role": "edge" },
    "snmp":            { "version": "v2c", "community": "REPLACE_ME" }
  },
  "rationale":   "Spoke router for Bogotá DC upgrade; brand/model from procurement sheet.",
  "source_refs": ["chat:msg-2026-09-13-001"]
}
```

| Field | Required | Notes |
|---|---|---|
| `schema_version` | yes | Must be `1`. Bumping this value signals a breaking change. |
| `ci.id` | yes | Must NOT collide with an existing `:CI.id` (backend rejects with `409 ci_id_collision`). |
| `ci.label` | yes | Human-readable name. |
| `ci.category` | yes | MUST equal a live `:Category.name` returned by `GET /api/categories`. |
| `ci.brand`, `ci.model`, `ci.serialNumber`, `ci.firmwareVersion`, `ci.ip`, `ci.owner`, `ci.location_name`, `ci.status`, `ci.pollingInterval` | no | Flattened CI fields. |
| `ci.metadata` | no | Free-form dict. Keys MUST NOT overlap with `id`, `label`, `type`, `brand`, `model`, `serialNumber`, `firmwareVersion`, `ip`, `snmp`, `location`. |
| `ci.snmp` | no | Dict shape `{version, community, port, ...}`. **See secret warning below.** |
| `rationale` | no | Free-text rationale (max 1024 chars). |
| `source_refs` | no | Array of provenance strings (chat message IDs, ticket keys, etc.) — max 16 entries. |

### DO NOT send real secrets

The audit service REDACTS these field patterns before persistence:

- `snmp.community`, `snmp.authKey`, `snmp.privKey`
- Any key matching `*key|*token|*secret|*password` (case-insensitive)

If you submit a real community string it will be saved as `<REDACTED>` in the
audit log. **The CMDB itself will store whatever you submit** — so prefer
placeholders like `"REPLACE_ME"` or leave the field empty and let the human
reviewer set the real value in `CIEditor` after approval.

---

## Error codes

| HTTP | `reason` | What it means |
|---|---|---|
| `201` | — | Proposal created. Response body has `proposal_id`, `version=1`. |
| `200` | `harness_result.denied=true` | Guardrail denied (cooldown or bulk threshold). NO `:CIProposal` was created. Retry after the indicated `cooldown_remaining_seconds`. |
| `400` | — | Bad request shape. |
| `403` | `missing_permission: AI_PROPOSE_CI required` | Caller lacks `AI_PROPOSE_CI`. |
| `409` | `ci_id_collision` | A `:CI` with that `id` already exists. |
| `409` | `version_conflict` | Stale `version` on approve/revoke. Re-fetch the proposal and retry. |
| `409` | `category_renamed` | The category is no longer in the live `:Category` list. Re-resolve from `/api/categories`. |
| `409` | `invalid_state` | The proposal is not in the expected state (e.g., approving an `APPROVED` proposal). |
| `422` | `unknown_category` | `ci.category` not in `/api/categories`. |
| `422` | `invalid_manifest` | Schema validation failed. See `errors` in the response body. |
| `429` | `cooldown_active` | The `propose_ci` cooldown blocks your submit. |
| `429` | `bulk_threshold` | You exceeded 5 proposals in the last 60 minutes. Slow down. |

---

## Python prompt template (copy-pasteable)

```python
import os
import requests

API = os.getenv("NEXGEN_API", "http://localhost:8000")
TOKEN = os.getenv("NEXGEN_TOKEN", "<bearer-jwt-with-AI_PROPOSE_CI>")

manifest = {
    "schema_version": 1,
    "ci": {
        "id":   "CI-N9X3K2",
        "label": "Core Router Bogotá",
        "category": "Router",
        "brand": "Cisco",
        "model": "ASR-1000",
        "ip":    "10.20.30.1",
        "metadata": {"rack": "R12"},
    },
    "rationale": "Spoke router for Bogotá DC upgrade.",
    "source_refs": ["chat:msg-2026-09-13-001"],
}

resp = requests.post(
    f"{API}/api/cmdb/proposals",
    json=manifest,
    headers={"Authorization": f"Bearer {TOKEN}"},
    timeout=10,
)
resp.raise_for_status()
data = resp.json()

if data.get("harness_result", {}).get("denied"):
    # Guardrail denied — back off and retry after cooldown.
    print("Denied:", data["harness_result"])
else:
    proposal_id = data["proposal_id"]
    print("Drafted:", proposal_id, "version", data["version"])
    # A human reviewer will see it at /proposals/cmdb and approve / revoke.
```

---

## Guardrails you should know about

1. **Cooldown** — at most 1 `propose_ci` submission per 120 seconds per agent
   (env `CMDB_PROPOSAL_COOLDOWN_SECONDS`, mirrors `ci_metadata_update`).
2. **Bulk threshold** — more than 5 proposals in the last 60 minutes from one
   agent → escalate or deny (env `CMDB_PROPOSAL_BULK_THRESHOLD=5`).
3. **Category must exist** — both at submit and at approve time.
4. **Optimistic version** — every approve/revoke requires `version`. First
   writer wins; concurrent attempts get `409 version_conflict`.
5. **TTL auto-revoke** — `DRAFT` proposals older than 30 days are auto-revoked
   by `backend/scripts/cmdb_proposal_ttl_sweep.py`. The sweep emits a
   `CI_PROPOSAL_REVOKE` audit row with `actor_role="SYSTEM"` and
   `revoke_reason="ttl_expired"`.

---

## Audit redaction reminder

The audit context is public to operators with `AUDIT_VIEW`. Secrets that match
the deny-list patterns above are stored as `"<REDACTED>"`. Submit placeholders
for credentials; populate them in `CIEditor` after the human reviewer approves.