# Apply Progress: fix-416-orphan-topology-backfill

## Size Exception
- Acknowledged: user accepted `size:exception` for the entire change (planning 1003 + implementation ~756 = 1760 lines).
- Reference: prior P0 precedent (`2026-08-01-fix-416-event-amplification-p2`) — same `size:exception` pattern.
- Cumulative changed lines vs `main` at this delegation boundary: **1659 insertions** (within 1760 budget; ~101 lines of headroom remain for WU-4..10).

## Note on test-command invocation
The user's stated command `cd backend && .venv/bin/python -m pytest openspec/scripts/tests/ -v`
won't resolve because `openspec/` lives at the repo root, not inside
`backend/`. The actual run command used (and that resolves cleanly) is:

```
backend/.venv/bin/python -m pytest openspec/scripts/tests/ -v    # run from repo root
```

Same `.venv`, same test path; just invoked from the repo root where
`openspec/scripts/tests/` exists. This deviation is purely cwd — the
testpath is unchanged.

## Overall Status
- WUs completed: 3/10 (this delegation covered WU-1..3)
- Total commits on branch since `main`: **8 commits** (1 planning + 7 implementation/scaffold)
- Changed lines since start of apply: **656** (1659 total − 1003 planning)
- Last pytest result: **42/42 PASS**
- Last `ruff check --config backend/ruff.toml openspec/scripts/`: **All checks passed!**
- Privacy sweep: **PASS** (zero matches)

## WU-1 — Scaffold + gitignore
- Status: done
- Commits:
  - `131b8bd` chore(scripts): scaffold openspec/scripts package with synthetic-id guard (RED)
  - `bea78f0` chore(gitignore): ignore openspec/scripts/output directory (GREEN)
- Tests: 3 (test_synthetic_id_regex_matches_pattern, test_openspec_scripts_output_is_gitignored, test_gitignore_contains_output_entry)
- Files touched:
  - `openspec/scripts/__init__.py` (new, empty)
  - `openspec/scripts/tests/__init__.py` (new, empty)
  - `openspec/scripts/tests/conftest.py` (new, SYNTHETIC_ID_RE + UUID regex + autouse `validate_fixture_ids` REQ-010 guard)
  - `openspec/scripts/tests/test_scaffold.py` (new, SCN-012 assertion + sanity regex check)
  - `.gitignore` (3 lines added)
- Notes:
  - Initial RED test commit ran with FAIL on the two `.gitignore` assertions (entry missing); GREEN commit flipped them to PASS.
  - The autouse `validate_fixture_ids` fixture was tightened mid-WU-3 (see WU-3 notes) to use `request._fixture_values` snapshot instead of `request.getfixturevalue` at teardown — prevents spurious teardown errors that previously masked the test outcome. Documented in WU-3 commit.

## WU-2 — Validation layer
- Status: done
- Commits:
  - `cc7af2d` test(orphan-cli): red tests for scope and relationship-type validators (RED)
  - `84eb1eb` feat(orphan-cli): validate --scope and --relationship-types allowlist (GREEN)
- Tests: 13 (4 validate_scope + 9 validate_relationship_types)
- Files touched:
  - `openspec/scripts/tests/test_validators.py` (new, 112 lines)
  - `openspec/scripts/cmdb_backfill_orphans.py` (new file but only ~55 lines in this WU)
- Notes:
  - REQ-001 / SCN-008 covered by 4 validate_scope tests (ap accepted, switch/router/empty rejected with exact message shape).
  - REQ-002 / AD-08 covered by 9 validate_relationship_types tests (None→default, explicit default accepted, CONNECTS_TO rejected, raw Cypher rejected, MANAGES/RUNS_ON accepted, duplicate dedupe, order preservation, bad-Apple rejection, empty list→default).
  - Strong triangulation already in place for both validators (multi-input coverage per spec scenarios).

## WU-3 — Output layer
- Status: done
- Commits:
  - `22ec57e` test(orphan-cli): red tests for output envelope and ci-id validation (RED)
  - `83000c7` feat(orphan-cli): strict JSON envelope and atomic output routing (GREEN impl + conftest teardown fix)
  - `fee79fa` style(orphan-cli): clean ruff violations for wu-1..3 (lint compliance)
- Tests: 26 (9 build_output_payload + 4 write_output + 13 _validate_ci_id, includes 9 parametrized rejections)
- Files touched:
  - `openspec/scripts/tests/test_output.py` (new, 260 lines)
  - `openspec/scripts/cmdb_backfill_orphans.py` (expanded to 165 lines — added build_output_payload, write_output, _validate_ci_id, _is_opaque_ci_id, _now_iso8601_utc, datetime imports, Module-level SYNTHETIC_ID_RE / _UUID_SHAPE_RE)
  - `openspec/scripts/tests/conftest.py` (tightened autouse fixture teardown)
- Notes:
  - REQ-003 / REQ-004: `build_output_payload` returns dict with EXACTLY `{as_of, scope, relationship_types, orphan_count, ci_ids}`, ISO 8601 UTC `as_of` with trailing `Z`, `orphan_count == len(ci_ids)`, non-opaque values stripped.
  - REQ-006: `write_output` uses `Path.write_text(...)` + `.tmp` + `Path.replace(target)` atomic write; no `.tmp` leftover, `tmp_path.parent.mkdir(parents=True, exist_ok=True)` for nested dirs.
  - `_validate_ci_id` uses `uuid.UUID(...)` for canonical UUID parsing (per spec direction); `_UUID_SHAPE_RE` regex pre-filters synthetic IDs only.
  - **PRIVACY NOTE**: the WU-1 scaffold and WU-3 RED commits originally used several issue-derived placeholder strings (AP names and a production IP from issue #416) as rejection-test fixtures and regex sanity checks. Per privacy policy, the working tree was sanitized to use neutral uppercase / IPv4-shaped placeholders (`REGION_TAG`, `10.99.99.99`, `REMOTE_SITE`, `UPPERCASE_TOKEN`, `OFFICE_TAG`). The original placeholder values are documented only by their neutral-shape names to keep the issue's identifying strings out of git history; refer to the upstream issue tracker for the original token mapping.
  - **Python version caveat**: project `backend/pyproject.toml` and `ruff.toml` target Python 3.11 (`datetime.UTC` alias). The local `.venv` is 3.9 so `datetime.UTC` is unavailable. Resolved via per-line `# noqa: UP017` on the single `timezone.utc` call site; CI's 3.11 runtime won't trigger UP017 at all.

## Privacy Sweep
- Result: **PASS** (working tree and git history)
- Last run: 2026-08-02
- Command: `grep -rE "<issue-derived rejection-test tokens and production IP from issue #416>" openspec/scripts/`
- Working tree status: zero matches.
- Git history status: zero matches across all branch commits (`git log main..HEAD --all -p` clean — see "History Cleanup Rebase" section below).

## TDD Cycle Evidence

| Task | RED commit | GREEN commit | REFACTOR | RED tests | Triangulation |
|------|------------|--------------|----------|-----------|---------------|
| WU-1 T-001..T-005 | `131b8bd` | `bea78f0` | mid-WU-3 conftest teardown tightens | 3 (sanity + 2 .gitignore assertions) | ✓ via gitignore + grep regex |
| WU-2 T-006..T-009 | `cc7af2d` | `84eb1eb` | — | 13 (4 scope + 9 rel types) | ✓ each validator has happy + 3+ edge/reject paths |
| WU-3 T-010..T-013 | `22ec57e` | `83000c7` | `fee79fa` ruff | 26 (9 payload + 4 write + 13 validate_ci_id) | ✓ payload covered for {keys, count, ISO, scope/rels passthrough, filter, dedupe, empty}; write_output covered for {file+empty stdout, stdout-only, atomic, pathlib}; _validate_ci_id with 9 parametrized negative shapes + 3 positive (synthetic, UUID, uppercase UUID) |

## Tests Summary
- Total tests written: 42 (3 + 13 + 26)
- Total tests passing: 42
- Layers used: Unit (42 — all are pure-function unit tests; no integration harness needed at this scope)
- Approval tests: None (no refactoring of legacy code; greenfield only)
- Pure functions created: 7 (validate_scope, validate_relationship_types, _validate_ci_id, _is_opaque_ci_id, _now_iso8601_utc, build_output_payload, write_output)

## Coverage Map (this delegation)
- REQ-001 (scope) → WU-2
- REQ-002 (rel allowlist) → WU-2
- REQ-003 (output schema) → WU-3
- REQ-004 (opaque IDs only) → WU-3
- REQ-009 (.gitignore) → WU-1
- REQ-010 (synthetic fixtures) → WU-1 conftest + autouse guard
- AD-01 (scope ap-only) → WU-2
- AD-03 (opaque IDs) → WU-3
- AD-05 (no real customer data) → WU-1 conftest + WU-3 privacy fixup
- AD-06 (gitignore) → WU-1
- AD-08 (rel allowlist) → WU-2
- AD-11 (scaffold) → WU-1
- SCN-008 (scope rejection) → WU-2 (unit) — wired into WU-9 integration
- SCN-012 (.gitignore) → WU-1

## Files NOT Touched (per scope)
- `backend/repositories/topology_repo.py` (per AD-12, self-contained script)
- `backend/services/snmp_service.py`
- `backend/main.py`
- `openspec/specs/event-write-time-correlation/*`
- Anything outside `openspec/scripts/` and `.gitignore`

## Stop Conditions Encountered
None. All 3 WUs landed green; 42/42 tests pass; ruff clean; privacy sweep clean (working tree); `.gitignore` has the required entry.

## Sizes
- WU-1: ~116 lines (scaffold + gitignore)
- WU-2: ~167 lines (validators)
- WU-3: ~373 lines (output layer + lint)
- WU-4..10: not yet started

## Recommended for Next Delegation
- Continue with WU-4 (audit line) using same pattern.
- Branch is ready to push: history-cleanup rebase already performed; no further orchestrator-driven history rewrites needed before push.

## History Cleanup Rebase (post-WU-3)
- Date: 2026-08-02
- Action: rebased commits `7978a05` (planning), `b624c09` (WU-1 scaffold), and `fe34025` (WU-3 RED) to remove issue-derived placeholder strings (AP names and a production IP from issue #416) that were originally used as rejection-test fixtures. Replaced with neutral placeholders (`REGION_TAG`, `10.99.99.99`, `REMOTE_SITE`, `UPPERCASE_TOKEN`, `OFFICE_TAG`) from the start of each commit. The original fixup commit was dropped (work folded into the originals). Sanitized the planning `tasks.md` T-041 privacy-sweep line, the WU-3 commit message body, and the apply-progress.md PRIVACY NOTE / Privacy Sweep sections to use neutral references only.
- Result: git history clean. Privacy sweep passes on both working tree and git history.
- Tests after rebase: 42/42 pass.
