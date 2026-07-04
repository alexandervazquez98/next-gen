# Apply Progress: Tunnel Health Normalization

## Change

feat-324-tunnel-health-normalization

## Mode

Strict TDD — focused Slice 2 pytest now runs in the authorized local backend virtual environment created with `/Users/macbook/.local/bin/python3.11`. Tests were written before production code, and the focused command is GREEN.

## Completed Tasks

- [x] 1.1 Service normalization RED tests written.
- [x] 1.2 Canonical link id RED tests written.
- [x] 2.1 Tunnel health service/models/link id implementation created.
- [x] 2.2 ICMP context kept separate from normalized status domain.
- [x] 3.1 Repository eligible-link tests written.
- [x] 3.2 Repository whitelist/scoping tests written.
- [x] 3.3 Repository scalar persistence/isolation tests written.
- [x] 4.1 Scoped tunnel lookup implemented.
- [x] 4.2 Latest-health scalar read/write helpers implemented.
- [x] 5.1 Router/API tests written.
- [x] 5.2 Deterministic API response body tests written.
- [x] 6.1 Authenticated tunnel health endpoint implemented.
- [x] 6.2 Router registered under `/api`.
- [x] 7.1 Refactor pass kept response shape deterministic.
- [x] Fix: repository read path now preserves persisted `tunnel_icmp_reason` for deterministic ICMP contexts, including `no_sample` and `failed`.
- [x] Fix: router endpoint now has oversized `link_id` 400 coverage before repository lookup.
- [x] 7.2 Focused pytest command executed with the authorized backend venv: 25 passed, 7 warnings.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `backend/tests/test_tunnel_health.py` | Unit | N/A (new) | ✅ Written before service existed | ✅ `backend/.venv/bin/python -m pytest ...` passed | ✅ Multiple authority/ICMP cases | ✅ Response semantics remain deterministic |
| 1.2 | `backend/tests/test_tunnel_health.py` | Unit | N/A (new) | ✅ Written before service existed | ✅ `backend/.venv/bin/python -m pytest ...` passed | ✅ Valid, invalid, unsafe, oversized cases | ✅ Canonical link identity stays bounded |
| 2.1 | `backend/tests/test_tunnel_health.py` | Unit | N/A (new) | ✅ Service tests existed before production code | ✅ Focused pytest passed | ✅ Canonical and invalid link id cases | ✅ Pure functions/models extracted |
| 2.2 | `backend/tests/test_tunnel_health.py` | Unit | N/A (new) | ✅ ICMP/status domain tests existed first | ✅ Focused pytest passed | ✅ UP/DOWN/UNKNOWN plus ICMP failure/missing public IP | ✅ Status literals constrain domain |
| 3.1 | `backend/tests/test_topology_tunnel_health.py` | Integration (mock Neo4j) | N/A (new helper tests) | ✅ Written before repository helpers existed | ✅ Focused pytest passed | ✅ Eligible medium and non-match/no-row cases | ✅ Query isolated to CI-to-CI tunnel relationship |
| 3.2 | `backend/tests/test_topology_tunnel_health.py` | Integration (mock Neo4j) | N/A (new helper tests) | ✅ Written before repository helpers existed | ✅ Focused pytest passed | ✅ Admin, scoped operator, invalid relationship cases | ✅ Whitelist validation occurs before DB access |
| 3.3 | `backend/tests/test_topology_tunnel_health.py` | Integration (mock Neo4j) | N/A (new helper tests) | ✅ Written before repository helpers existed | ✅ Focused pytest passed | ✅ Read/write and forbidden Cypher assertions | ✅ Scalar property mapping centralized |
| 4.1 | `backend/tests/test_topology_tunnel_health.py` | Integration (mock Neo4j) | N/A (new helper) | ✅ Repository tests existed first | ✅ Focused pytest passed | ✅ Scoped exact link lookup covered | ✅ Reused existing relationship validator |
| 4.2 | `backend/tests/test_topology_tunnel_health.py` | Integration (mock Neo4j) | N/A (new helper) | ✅ Persistence tests existed first | ✅ Focused pytest passed | ✅ Scalar property assertions covered | ✅ No metric/event/status mutation in helper |
| 5.1 | `backend/tests/test_routers_tunnels.py` | API | N/A (new route) | ✅ Written before router existed | ✅ Focused pytest passed | ✅ 200/400/404 cases | ✅ Router returns response model |
| 5.2 | `backend/tests/test_routers_tunnels.py` | API | N/A (new route) | ✅ Written before router existed | ✅ Focused pytest passed | ✅ sample/no-sample/missing-public-IP bodies | ✅ Deterministic model response |
| 6.1 | `backend/tests/test_routers_tunnels.py` | API | N/A (new route) | ✅ Router tests existed first | ✅ Focused pytest passed | ✅ scoped repository call and error mapping | ✅ Small route boundary |
| 6.2 | `backend/tests/test_routers_tunnels.py` | API | Existing router registration expectation | ✅ Router registration expected by API tests | ✅ Focused pytest passed | ➖ Registration is structural | ✅ No frontend/poller/vendor changes |
| 7.1 | All focused tests | Unit/Integration/API | N/A | ✅ Refactor constrained by prior tests | ✅ Focused pytest passed | ✅ Focused Slice 2 suite executed | ✅ No production changes needed during verification |
| 7.2 | Focused pytest command | Unit/Integration/API | N/A | ✅ Previously blocked, now unblocked by authorized venv | ✅ 25 passed, 7 warnings | N/A | ✅ GREEN evidence recorded |
| Fix: persisted ICMP reason readback | `backend/tests/test_topology_tunnel_health.py` | Repository (mock Neo4j) | Focused pytest validates regression | ✅ Added repository read-path regression before production fix | ✅ Focused pytest passed | ✅ Covers `no_sample` and `failed` persisted reasons with public IPs present | ✅ Readback preserves deterministic ICMP context |
| Fix: oversized endpoint mapping | `backend/tests/test_routers_tunnels.py` | API | Focused pytest validates regression | ✅ Added endpoint 400 regression before no production change was needed | ✅ Focused pytest passed | ✅ Asserts repository is not called for oversized decoded payload | ✅ Endpoint rejects oversized id before repository lookup |

## Test Commands and Evidence

- RED command attempted: `uv run pytest backend/tests/test_tunnel_health.py backend/tests/test_topology_tunnel_health.py backend/tests/test_routers_tunnels.py` from repo root → blocked: `zsh:1: command not found: uv`.
- Fallback attempted: `python -m pytest tests/test_tunnel_health.py tests/test_topology_tunnel_health.py tests/test_routers_tunnels.py` from `backend/` → blocked: `zsh:1: command not found: python`.
- Fallback attempted: `python3 -m pytest tests/test_tunnel_health.py tests/test_topology_tunnel_health.py tests/test_routers_tunnels.py` from `backend/` → blocked: `/Library/Developer/CommandLineTools/usr/bin/python3: No module named pytest`.
- Syntax validation: `python3 -m py_compile backend/services/tunnel_health.py backend/repositories/topology_repo.py backend/routers/tunnels.py backend/main.py backend/tests/test_tunnel_health.py backend/tests/test_topology_tunnel_health.py backend/tests/test_routers_tunnels.py` → passed.
- Fix rerun attempted: `uv run pytest backend/tests/test_tunnel_health.py backend/tests/test_topology_tunnel_health.py backend/tests/test_routers_tunnels.py` from repo root → blocked: `zsh:1: command not found: uv`.
- Fix rerun fallback attempted: `python -m pytest tests/test_tunnel_health.py tests/test_topology_tunnel_health.py tests/test_routers_tunnels.py` from `backend/` → blocked: `zsh:1: command not found: python`.
- Fix rerun fallback attempted: `python3 -m pytest tests/test_tunnel_health.py tests/test_topology_tunnel_health.py tests/test_routers_tunnels.py` from `backend/` → blocked: `/Library/Developer/CommandLineTools/usr/bin/python3: No module named pytest`.
- Fix syntax validation: `python3 -m py_compile backend/services/tunnel_health.py backend/repositories/topology_repo.py backend/routers/tunnels.py backend/main.py backend/tests/test_tunnel_health.py backend/tests/test_topology_tunnel_health.py backend/tests/test_routers_tunnels.py` → passed.
- Environment setup: `/Users/macbook/.local/bin/python3.11 -m venv backend/.venv` followed by `backend/.venv/bin/python -m pip install --upgrade pip` and `backend/.venv/bin/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt` → passed.
- Focused GREEN command from repo root: `backend/.venv/bin/python -m pytest backend/tests/test_tunnel_health.py backend/tests/test_topology_tunnel_health.py backend/tests/test_routers_tunnels.py` → 25 passed, 7 warnings in 65.53s.

## Files Changed

- `backend/services/tunnel_health.py` — pure models, canonical link id encode/decode, and authority-only normalization.
- `backend/repositories/topology_repo.py` — scoped eligible tunnel lookup and latest-health scalar relationship read/write helpers.
- `backend/routers/tunnels.py` — authenticated `GET /api/tunnels/{link_id}/health` endpoint.
- `backend/main.py` — registered tunnels router under `/api`.
- `backend/tests/test_tunnel_health.py` — service/link id tests.
- `backend/tests/test_topology_tunnel_health.py` — repository helper tests.
- `backend/tests/test_routers_tunnels.py` — API endpoint tests.
- `backend/services/tunnel_health.py` — `TunnelIcmpSample` now carries an optional persisted ICMP reason and normalization preserves deterministic persisted ICMP contexts.
- `backend/repositories/topology_repo.py` — repository read mapping now passes `tunnel_icmp_reason` back into normalization.
- `backend/tests/test_topology_tunnel_health.py` — added regression coverage for persisted `no_sample` and `failed` ICMP reasons through the real repository read helper.
- `backend/tests/test_routers_tunnels.py` — added endpoint-level oversized `link_id` 400 coverage and repository bypass assertion.
- `openspec/changes/feat-324-tunnel-health-normalization/tasks.md` — marked focused pytest verification complete after GREEN venv execution.
- `openspec/changes/feat-324-tunnel-health-normalization/apply-progress.md` — this progress artifact, updated with GREEN pytest evidence.

## Deviations from Design

None — implementation matches design. Automated GREEN evidence is now available from the authorized backend venv.

## Remaining Work

- [x] Focused Slice 2 pytest is GREEN. No remaining Slice 2 apply-verification work in this batch.

## Pre-PR Blocker Remediation Addendum

### Date

2026-07-04

### Completed Fixes

- [x] Installed CI-pinned `ruff==0.15.18` and `black==26.5.1` into the worktree-local `backend/.venv` only.
- [x] Applied Ruff/Black-compatible formatting and lint fixes to changed backend Python files.
- [x] Added API coverage proving unauthenticated requests are rejected before repository lookup.
- [x] Added API coverage proving operator/admin `allowed_locations` and `is_admin` values are forwarded to `topology_repo.get_tunnel_health_link()`.
- [x] Added canonical link-id hardening coverage for padded and non-canonical field-order payloads.
- [x] Added repository read-model coverage for an eligible tunnel row with no tunnel health properties, returning deterministic `UNKNOWN` / `no_sample` context.

### TDD Cycle Evidence Addendum

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| Pre-PR auth/scope blocker | `backend/tests/test_routers_tunnels.py` | API | ✅ Existing focused suite was known GREEN before blocker fix | ✅ Added failing assertions for unauthenticated rejection and scope forwarding | ✅ Focused suite passed: 30 passed, 7 warnings | ✅ Operator and admin forwarding plus unauthenticated rejection | ✅ Router uses `Annotated[User, Depends(...)]` to satisfy Ruff B008 without behavior change |
| Pre-PR canonical/no-sample warnings | `backend/tests/test_tunnel_health.py`, `backend/tests/test_topology_tunnel_health.py` | Unit / repository | ✅ Existing focused suite was known GREEN before blocker fix | ✅ Added failing coverage for padded/non-canonical ids and no-health eligible row behavior | ✅ Focused suite passed: 30 passed, 7 warnings | ✅ Padded id, non-canonical order, and eligible no-sample row cases | ✅ `_row_value()` fallback avoids SIM401 while preserving missing-key defaults |
| Pre-PR lint blocker | Changed backend Python files | Static | ✅ Ruff/Black initially reported blockers | ✅ Local CI-pinned Ruff/Black checks reproduced lint/format failures | ✅ Ruff and Black checks passed | N/A | ✅ Applied import ordering, Black formatting, SIM401/SIM114 fixes, and FastAPI dependency annotation |

### Test and Lint Evidence

- Focused suite: `backend/.venv/bin/python -m pytest backend/tests/test_tunnel_health.py backend/tests/test_topology_tunnel_health.py backend/tests/test_routers_tunnels.py` → 30 passed, 7 warnings in 3.67s.
- Compatibility suite: `backend/.venv/bin/python -m pytest backend/tests/test_topology_relationships.py backend/tests/test_routers_links.py backend/tests/test_topology_repo_nodes.py` → 52 passed, 7 warnings in 3.11s.
- Ruff: `backend/.venv/bin/python -m ruff check --config backend/ruff.toml backend/services/tunnel_health.py backend/repositories/topology_repo.py backend/routers/tunnels.py backend/tests/test_tunnel_health.py backend/tests/test_topology_tunnel_health.py backend/tests/test_routers_tunnels.py backend/main.py` → passed.
- Black: `backend/.venv/bin/python -m black --check backend/services/tunnel_health.py backend/repositories/topology_repo.py backend/routers/tunnels.py backend/tests/test_tunnel_health.py backend/tests/test_topology_tunnel_health.py backend/tests/test_routers_tunnels.py backend/main.py` → 7 files would be left unchanged.

## Pre-PR CI-Equivalent Lint Addendum

### Date

2026-07-04

### Completed Fix

- [x] Reproduced the remaining CI-equivalent Ruff blocker from `backend/` with `--config ruff.toml`; Ruff 0.15.18 reported I001 import-ordering failures in the seven changed backend Python files.
- [x] Ran Ruff's fixer from the same `backend/` working directory to organize imports without behavior changes.
- [x] Re-ran Ruff, Black, focused Slice 2 pytest, and Slice 1 compatibility pytest from `backend/`; all passed.

### CI-Equivalent Evidence

- Reproduced blocker: from `backend/`, `.venv/bin/python -m ruff check --config ruff.toml main.py repositories/topology_repo.py routers/tunnels.py services/tunnel_health.py tests/test_tunnel_health.py tests/test_topology_tunnel_health.py tests/test_routers_tunnels.py` → 7 I001 errors.
- Fix command: from `backend/`, `.venv/bin/python -m ruff check --config ruff.toml --fix main.py repositories/topology_repo.py routers/tunnels.py services/tunnel_health.py tests/test_tunnel_health.py tests/test_topology_tunnel_health.py tests/test_routers_tunnels.py` → `Found 7 errors (7 fixed, 0 remaining).`
- Ruff verification: from `backend/`, `.venv/bin/python -m ruff check --config ruff.toml main.py repositories/topology_repo.py routers/tunnels.py services/tunnel_health.py tests/test_tunnel_health.py tests/test_topology_tunnel_health.py tests/test_routers_tunnels.py` → `All checks passed!`
- Black verification: from `backend/`, `.venv/bin/python -m black --check main.py repositories/topology_repo.py routers/tunnels.py services/tunnel_health.py tests/test_tunnel_health.py tests/test_topology_tunnel_health.py tests/test_routers_tunnels.py` → `7 files would be left unchanged.`
- Focused suite: from `backend/`, `.venv/bin/python -m pytest tests/test_tunnel_health.py tests/test_topology_tunnel_health.py tests/test_routers_tunnels.py` → 30 passed, 7 warnings.
- Compatibility suite: from `backend/`, `.venv/bin/python -m pytest tests/test_topology_relationships.py tests/test_routers_links.py tests/test_topology_repo_nodes.py` → 52 passed, 7 warnings.
