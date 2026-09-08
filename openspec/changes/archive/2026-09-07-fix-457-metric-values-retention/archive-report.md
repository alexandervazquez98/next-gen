# Archive Report: `fix-457-metric-values-retention`

**Change**: `fix-457-metric-values-retention`
**Issue**: #457 — feat(metrics): add retention policy to `metric_values` TimescaleDB hypertable
**Capability spec**: `openspec/specs/metric-values-retention/spec.md` (canonical, retained)
**Archived on**: 2026-09-07
**SDD cycle**: closed
**Archive verdict**: PASS WITH WARNINGS (per orchestrator final-state brief)
**Final release**: v1.16.1 (tag re-pointed to commit `7823594`)

## 1. What Shipped

### 1.1 Implementation commits (squash-merged to `main` via PR #463)

| SHA | Work-unit | Title |
|---|---|---|
| `c1fa4a8` | W1 | `feat(metrics): add idempotent apply_metric_retention wrapper for TimescaleDB (#457, W1)` |
| `49b2296` | W2 | `feat(metrics): wire metric_values retention scheduler + boot-time apply (#457, W2)` |
| `0c66b7c` | W3 | `chore(metrics): expose METRIC_RETENTION_* env vars + retire docs caveat (#457, W3)` |
| `d56110b` | W4 | `test(metrics): lock out-of-window exclusion semantics for metric_values retention (#457, W4)` |
| `9e927cf` | post-W2 | `fix(metrics): relocate boot-time retention apply from metric_repo to main startup` |
| `e2ab811` | sdd-apply | `chore(sdd): mark fix-457-metric-values-retention tasks complete` |
| `22df002` | sdd-apply | `chore(sdd): add proposal, design, and delta/full specs for fix-457-metric-values-retention` |
| `177eb39` | merge | `feat(metrics): add retention policy to metric_values TimescaleDB hypertable (#457) (#463)` (squash-merge of PR #463 to `main`) |
| `7823594` | release | `chore(release): update v1.16.1 CHANGELOG to include #457 (PR #463) and #461 (PR #464)` (current `main` HEAD, tag `v1.16.1` re-pointed here) |

**Note on SHA `cfba0ea`**: the orchestrator's launch brief referenced `cfba0ea` as the W1 commit SHA. Repository evidence shows `cfba0ea` is `feat(ai-chat): add useChatPreferences + useResizableHandle hooks (#461, W1)` — i.e. it is a #461 (AI chat) commit, not #457. The correct #457 W1 SHA is `c1fa4a8`. The orchestrator's brief carried a copy-paste artifact; the archive report records the accurate SHAs from `git log` per the Final-State Authority hierarchy (repository evidence outranks intermediate snapshot). This is recorded as an explicit correction rather than a silent rewrite.

### 1.2 Capability spec content

- **Specification surface** (REQ-MVR-001 .. REQ-MVR-006, 12 scenarios, byte-identical between delta and canonical):
  - REQ-MVR-001 — TimeScaleDB retention policy on `metric_values` (boot-time apply + scheduler defensive re-apply).
  - REQ-MVR-002 — Operator-configurable retention interval via `METRIC_RETENTION_DAYS` (default 90, range 1..3650, invalid → default).
  - REQ-MVR-003 — Kill-switch via `METRIC_RETENTION_ENABLED` (default `true`).
  - REQ-MVR-004 — Idempotent `apply_metric_retention` (no duplicate `timescaledb_information.jobs` rows on repeat calls).
  - REQ-MVR-005 — Retention excludes out-of-window rows from standard `metric_values` queries once the policy is active.
  - REQ-MVR-006 — Forward-looking semantics: no retroactive prune, no out-of-process purge.

- **Delta vs canonical sync**: `diff -r openspec/changes/fix-457-metric-values-retention/specs/metric-values-retention/spec.md openspec/specs/metric-values-retention/spec.md` is **empty** — the delta spec already mirrored the canonical capability spec during the spec phase. No further sync required during archive.

### 1.3 Acceptance criteria from issue #457 (5/5 met)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | One idempotent policy exists with the 90-day default | met | `c1fa4a8` + `49b2296` + `d56110b` |
| 2 | 30-day interval and all five strict-TDD cases pass | met | `d56110b` (out-of-window exclusion); strict-TDD cases for idempotency, 30-day override, kill-switch, invalid-env, out-of-window all covered by `tests/test_retention_service.py` and `tests/test_metric_retention_scheduler.py` |
| 3 | Disabled/invalid settings behave safely | met | REQ-MVR-002 + REQ-MVR-003 scenarios; `METRIC_RETENTION_ENABLED=false` skips registration; invalid `METRIC_RETENTION_DAYS` falls back to 90 with `WARNING` |
| 4 | Boot and scheduler paths cover fresh and existing installs | met | `49b2296` (boot-time apply inside `create_hypertable`); `9e927cf` (post-W2 relocation of boot-time apply to `main.py` startup — defensive re-apply on each boot); 6 h `CronTrigger` defensive scheduler |
| 5 | Runbook and `time-series` contract document evidence and forward-only behavior | met | `0c66b7c` updates `docs/polling-pipeline-tuning.md` (line 109 caveat retired, cross-reference to issue #457 and REQ-MVR-006 added); `.env.example` exposes both env vars; canonical capability spec at `openspec/specs/metric-values-retention/spec.md` |

## 2. Verification Results

Per orchestrator final-state brief (post-implementation, overriding intermediate snapshots):

- **Verdict**: PASS WITH WARNINGS.
- **Unit tests (touched files)**: 25/25 green — 13 retention tests (`tests/test_retention_service.py`), 2 scheduler tests (`tests/test_metric_retention_scheduler.py`), 10 event_prune regression tests (`tests/test_event_prune_scheduler.py`) — no regression on the precedent scheduler suite.
- **Lint/format (touched files)**: ruff + black clean on `backend/services/retention_service.py`, `backend/repositories/metric_repo.py`, `backend/main.py`, `backend/config.py`, `backend/tests/test_retention_service.py`, `backend/tests/test_metric_retention_scheduler.py`, `.env.example`, `docs/polling-pipeline-tuning.md`.
- **Full backend test suite (relevant files)**: green — no cross-cutting regressions.

No CRITICAL findings; any warnings recorded are non-blocking and below the strict-archive-blocking threshold.

## 3. Risks and Caveats

Recorded for future readers of the archive audit trail:

1. **Forward-only semantics** (REQ-MVR-006): existing rows older than the configured interval at deploy time are not pruned by the policy itself. Operators upgrading from a deployment with accumulated metrics will continue to see existing rows in `metric_values` until each chunk's age crosses the threshold and the scheduler drops it on roll-over. No backfill is added.

2. **W2 boot-time apply was relocated** in commit `9e927cf`: the original W2 design called `apply_metric_retention` from inside `metric_repo.create_hypertable`; the post-W2 fix moved the boot-time defensive re-apply into `backend/main.py` startup. This keeps the policy application decoupled from the hypertable-creation ORM transaction while preserving the REQ-MVR-001 scenario-1 contract (fresh installs get the policy on first boot; established deployments get it via the 6 h scheduler tick).

3. **`verify-report.md` not persisted to disk**: no `verify-report.md` exists in the change folder and `git log -- openspec/changes/fix-457-metric-values-retention/verify-report.md` is empty. The verification findings reported above come from the orchestrator's final-state brief (per Final-State Authority #2 — explicit final-state facts in the launch prompt outrank intermediate snapshots). Future readers should not infer that a verify-report.md was suppressed; none was authored as a persistent artifact.

4. **`openspec/specs/metric-values-retention/spec.md` is the canonical capability spec**: it stays in place after archive. The delta spec at `openspec/changes/fix-457-metric-values-retention/specs/metric-values-retention/spec.md` is byte-identical to it and moves to the archive with the change folder.

## 4. Tasks Reconciliation

All 17 tasks in `tasks.md` are marked done (W1: 6, W2: 5, W3: 3, W4: 3). The archived `tasks.md` retains the same state — no stale unchecked implementation tasks at archive time. **Task Completion Gate: PASSED.**

## 5. Archive Operation

### Source → destination

- **Source**: `openspec/changes/fix-457-metric-values-retention/`
- **Destination**: `openspec/changes/archive/2026-09-07-fix-457-metric-values-retention/`
- **Mode**: mechanical `git mv` (folder is git-tracked) — file content did not pass through the model Read/Write path.

### Mechanical copy contract (MANDATORY)

The Mechanical Copy Contract applies because the delta spec and canonical spec were already byte-identical (`diff -r` empty). No spec-sync write was required; only the folder move was performed.

- **Spec sync readback**: `diff -r openspec/changes/fix-457-metric-values-retention/specs/metric-values-retention/spec.md openspec/specs/metric-values-retention/spec.md` → empty (no differences).
- **Archive move readback**: `diff -r <snapshot_of_source> <destination>` → empty (no differences). Verbatim `diff -r` output is recorded in the archive commit message and in the phase result returned to the orchestrator.

## 6. Final Release State

- **Tag**: `v1.16.1` → `7823594 chore(release): update v1.16.1 CHANGELOG to include #457 (PR #463) and #461 (PR #464)` (current `main` HEAD).
- **CHANGELOG [1.16.1]** entry (line 20): "TimescaleDB `metric_values` hypertable now has a retention policy (#457, PR #463)".
- **SDD cycle**: closed; next change may proceed.

## 7. Next Step

Hand off to the orchestrator. The next SDD cycle target is `feat-461-ai-chat-resizable` (or whichever the orchestrator routes next); this change is fully archived.
