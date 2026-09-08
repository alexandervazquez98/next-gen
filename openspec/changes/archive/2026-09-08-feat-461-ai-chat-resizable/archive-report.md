# Archive Report: `feat-461-ai-chat-resizable`

**Change**: `feat-461-ai-chat-resizable`
**Issue**: #461 — feat(ai-chat): make AI chat panel resizable (drag width) and increase base font size
**Capability spec**: `openspec/specs/ai-chat-panel-layout/spec.md` (canonical, retained — new capability)
**Archived on**: 2026-09-08
**SDD cycle**: closed
**Archive verdict**: PASS WITH WARNINGS (per orchestrator final-state brief; upgrade from FAIL → PASS WITH WARNINGS after remediation commit `397c629` closed REQ-APL-004 runtime-coverage gap)
**Final release**: v1.16.1 (tag re-pointed to commit `7823594`)

## 1. What Shipped

### 1.1 Implementation commits (squash-merged to `main` via PR #464)

| SHA | Work-unit | Title |
|---|---|---|
| `cfba0ea` | W1 | feat(ai-chat): add useChatPreferences + useResizableHandle hooks |
| `dd66009` | W2 | feat(ai-chat): wire drag handle + responsive drawer + font bump |
| `4b944a0` | W3 | chore(ai-chat): cap with lint+format clean and full frontend suite green |
| `621d0bb` | sdd-apply | chore(sdd): add proposal, design, delta/full specs |
| `397c629` | remediation | test(ai-chat): add App-level integration test for REQ-APL-004 |
| `c6bbce5` | chore(lint) | chore(lint): silence pre-existing DOMException no-undef + no-console warnings in AIAgentConsole |
| `f696d87` | merge | feat(ai-chat): make AI chat panel resizable + bump base font size (#461) (#464) — squash-merge of PR #464 to `main` |
| `7823594` | release | chore(release): update v1.16.1 CHANGELOG to include #457 (PR #463) and #461 (PR #464) — current `main` HEAD, tag `v1.16.1` re-pointed here |

Note on the `c6bbce5` chore(lint) commit: this commit is recorded as shipped in the brief and is present in the branch's commit history but does not appear in the squash-merge single-SHA PR summary `f696d87`. It is included here for audit-trail completeness because it documents the closure of pre-existing lint warnings in `AIAgentConsole.tsx` and its test file (introduced by commits `dbd0857` and `1ffefe1`), which were called out as a WARNING in the verify-report.

### 1.2 Capability spec content

- **Specification surface** (REQ-APL-001 .. REQ-APL-006, 17 scenarios, byte-identical between delta and canonical):
  - REQ-APL-001 — Panel is horizontally resizable via a drag handle (clamped `[320, 720]` px, real-time updates).
  - REQ-APL-002 — Panel width persists across page reloads via `localStorage['nexgen.aiChat.width']`; default 480px; invalid stored values fall back to 480 without throwing.
  - REQ-APL-003 — Double-click the handle resets width to 480px and persists.
  - REQ-APL-004 — Below 768px viewport the panel renders as a full-width drawer; ≥ 768px reverts to fixed-sidebar mode; drag disabled in drawer mode.
  - REQ-APL-005 — In-panel typography is at least `text-base` (16px) for messages/input and at least `text-sm` (14px) for header/footer labels.
  - REQ-APL-006 — `useChatPreferences()` is the single source of truth, returning `{ width, setWidth, fontScale, setFontScale }`; `fontScale` defaults to `1` as dormant API surface.

- **Delta vs canonical sync**: `diff -r openspec/changes/feat-461-ai-chat-resizable/specs/ai-chat-panel-layout/spec.md openspec/specs/ai-chat-panel-layout/spec.md` is **empty** — the delta spec already mirrored the canonical capability spec during the spec phase. No further sync required during archive.

### 1.3 Acceptance criteria from issue #461 (7/7 met)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Operator can drag the left edge of the panel to widen or narrow it; clamp `[320, 720]` px enforced | met | `cfba0ea` (hooks) + `dd66009` (App.tsx wiring); unit tests in `useResizableHandle.test.ts` cover upper/lower clamp + listener add/remove + non-handle no-op |
| 2 | Width persists across full page reloads via `localStorage` key `nexgen.aiChat.width` | met | `useChatPreferences` hook + App.tsx mount-time read; `useChatPreferences.test.ts` covers default 480, restore from `"600"`, invalid `"-1"`/`"9999"`/`"abc"` fallback, debounced 250ms write, unmount clears timer |
| 3 | Double-click the handle resets width to the default (480px) and persists | met | `onDoubleClick` in `useResizableHandle` → `setWidth(480)`; test covers reset 640→480 plus the persistence path |
| 4 | Below 768px viewport, the panel becomes a full-width overlay drawer (not a narrow sidebar) | met | `App.tsx:72-86, 281-294` (`isOverlay` state + debounced `resize` listener at 250ms); 4 new App-level integration tests in `__tests__/App.test.tsx` (added by remediation `397c629`) cover initial 600px drawer, initial 1024px sidebar, sidebar→drawer transition, and drawer→sidebar transition |
| 5 | Message body and input font are at least `text-base` (16px); no `text-xs` remains in user-facing message / header / input areas | met | `AIAgentConsole.tsx` line 87 (`text-sm` header), line 98 (`text-base` bubble), line 127 (`text-base` input); `text-[10px]` chrome on model label and loading-bounce dots preserved as exempt |
| 6 | `frontend/components/__tests__/AIAgentConsole.test.tsx` snapshots and assertions updated; full frontend test suite (`cd frontend && corepack pnpm test:run`) green | met | 3 new typography assertions added at `AIAgentConsole.test.tsx:76-102`; full suite green at **609/609 across 75 files** (was 605; +4 from `__tests__/App.test.tsx`) |
| 7 | No regressions on `SystemDashboard` or `MonitoringConsole` routes that include the chat | met | `App.tsx` change scoped to aside swap + drag handle + responsive drawer; full suite green covers both routes and `App.itsm-route.test.tsx` |

## 2. Verification Results

Per orchestrator final-state brief (post-implementation, overriding intermediate snapshots):

- **Verdict**: PASS WITH WARNINGS (upgraded from FAIL after remediation commit `397c629`).
- **Requirements**: 6/6 satisfied.
- **Scenarios**: 17/17 covered by passing tests.
- **Test layer distribution**:
  - Unit (hooks): 12 tests in 2 files — `useChatPreferences.test.ts` (7), `useResizableHandle.test.ts` (5 → corrected from 3 after listener-cleanup coverage expansion; verify-report records 12 hook tests total).
  - Integration (component): 7 tests in 1 file — `AIAgentConsole.test.tsx`.
  - Integration (App-level, REQ-APL-004): 4 tests in 1 file — `__tests__/App.test.tsx` (new in remediation `397c629`).
  - Total new tests: 23 (19 added in initial W1/W2 + 4 added in remediation). The orchestrator brief states "19 new tests + 4 integration tests"; the 19 figure is the W1+W2 contribution and the 4 are the REQ-APL-004 remediation tests.
- **Full frontend Vitest suite**: **609/609 green across 75 files** (was 605 pre-change; +4 from the remediation test file).
- **Lint/format (touched files)**: ESLint + Prettier clean on every file touched by this change. Pre-existing lint issues in `AIAgentConsole.tsx` (L63 `DOMException no-undef`, L67 `console.error no-console`) and `__tests__/AIAgentConsole.test.tsx` (L31 `DOMException no-undef`) were silenced by chore(lint) commit `c6bbce5`.
- **CRITICAL findings**: 0.

No CRITICAL findings; any warnings recorded are non-blocking and below the strict-archive-blocking threshold.

## 3. Risks and Caveats

Recorded for future readers of the archive audit trail:

1. **REQ-APL-001 Scenario 1 pixel-precise styling is code-inspected only.** The drag-handle visual attributes (6px width, `left: 0`, `cursor: col-resize`) are stable string-contracts in the JSX at `frontend/App.tsx:284-294` and are not asserted to pixel precision in any test. Pointerdown response is unit-tested at hook level; the App-level integration test in `__tests__/App.test.tsx` now covers handle presence/absence across sidebar vs. drawer modes. This is acceptable; if future regression is suspected, add a `getComputedStyle` assertion in `__tests__/App.test.tsx`.

2. **Debounce timing constants are duplicated.** `useChatPreferences.ts` exports `DEBOUNCE_MS = 250` and `App.tsx` uses the same 250ms value inline for the `resize` listener. If the value is ever changed, both sites must be updated (no shared constant for the `resize` debounce). The test in `__tests__/App.test.tsx` advances fake timers in a 200ms/+100ms split that proves the debounce is real but is tied to the 250ms value.

3. **Design doc signature drift.** Per verify-report §11 SUGGESTION, `design.md` documents `useResizableHandle(setWidth, options?)` but the actual signature diverged to `useResizableHandle(width, setWidth, options?)` (drag math needs the current width as a closure value). The archive retains the design as-is for audit fidelity; future readers should treat the design doc as illustrative on this point and consult `frontend/hooks/useResizableHandle.ts` for the live contract.

4. **`useChatPreferences().fontScale` is dormant API surface.** Per the proposal's explicit scope decision, the hook exposes `fontScale` (default `1`) and `setFontScale` so that a future font-scale UI slice is a one-line consumer. No UI multiplies styles by `fontScale` in this change. The acceptance criterion forbids shipping the UI yet — reviewers should expect to see the field with no consumer.

5. **No E2E coverage.** Playwright is available (`playwright.config.ts`) but no scenarios were authored for this change. jsdom-based integration tests in `__tests__/App.test.tsx` cover the responsive-drawer logic; if a real-browser check is needed later (e.g. CSS engine assertions at viewport 600px), the test scaffold lives in the existing Playwright config.

6. **Pre-existing lint issues closed by `c6bbce5`, not in scope of #461.** The `DOMException no-undef` and `console.error no-console` warnings in `AIAgentConsole.tsx` and its test file (predating #461, introduced by `dbd0857` and `1ffefe1`) were cleaned up as a hygiene commit on the same branch. They are not regressions introduced by #461; they were closed opportunistically. Future readers of `git log frontend/components/AIAgentConsole.tsx` should not attribute the suppression to #461's primary scope.

7. **`openspec/specs/ai-chat-panel-layout/spec.md` is the canonical capability spec** (a NEW capability created by this change). It stays in place after archive as the source of truth for the AI chat panel layout behavior. The delta spec at `openspec/changes/feat-461-ai-chat-resizable/specs/ai-chat-panel-layout/spec.md` is byte-identical to it and moves to the archive with the change folder.

## 4. Tasks Reconciliation

All 12 tasks in `tasks.md` are marked complete (W1: 5, W2: 4, W3: 3). The archived `tasks.md` retains the same state — no stale unchecked implementation tasks at archive time. **Task Completion Gate: PASSED.**

## 5. Archive Operation

### Source → destination

- **Source**: `openspec/changes/feat-461-ai-chat-resizable/`
- **Destination**: `openspec/changes/archive/2026-09-08-feat-461-ai-chat-resizable/`
- **Mode**: mechanical `git mv` (folder is git-tracked) — file content did not pass through the model Read/Write path.

### Mechanical copy contract (MANDATORY)

The Mechanical Copy Contract applies because the delta spec and canonical spec were already byte-identical (`diff -r` empty). No spec-sync write was required; only the folder move was performed.

- **Spec sync readback**: `diff -r openspec/changes/feat-461-ai-chat-resizable/specs/ai-chat-panel-layout/spec.md openspec/specs/ai-chat-panel-layout/spec.md` → empty (no differences).
- **Archive move readback**: `diff -r <snapshot_of_source> <destination>` → empty (no differences). Verbatim `diff -r` output is recorded in the archive commit message and in the phase result returned to the orchestrator.

## 6. Final Release State

- **Tag**: `v1.16.1` → `7823594 chore(release): update v1.16.1 CHANGELOG to include #457 (PR #463) and #461 (PR #464)` (current `main` HEAD).
- **CHANGELOG [1.16.1]** entry (line 16): "AI chat panel is now resizable (drag handle) and bumps base font size (#461, PR #464)".
- **SDD cycle**: closed; next change may proceed.

## 7. Next Step

Hand off to the orchestrator. This change is fully archived. The working branch (`/private/tmp/next-gen-main-check`) is 1 commit ahead of `origin/main` (the archive commit itself); **DO NOT push to origin** — local commit only per the launch brief.
