# Tasks: AI Chat Panel Resizable + Typography Bump

> Change: `feat-461-ai-chat-resizable` · Issue: #461 · Branch: `feat/461-ai-chat-resizable`
> Delivery: **single-pr**, max LOC 800, three commits (W1 → W2 → W3).
> Stack: React 19.2.3 · TypeScript 5.8 · Vitest 4.1 · jsdom · Tailwind 4.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 250-350 |
| 400-line budget risk | Low |
| 800-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | single PR, 3 commits |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |
| Per-commit LOC ceiling | 250 |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| W1 | Hooks land (state + drag math) | PR 1 | `pnpm vitest run hooks/useChatPreferences.test.ts hooks/useResizableHandle.test.ts` | N/A — hooks, not a route | Revert W1 leaves `App.tsx` unchanged; chat falls back to existing `w-96`; localStorage untouched. |
| W2 | Integration + typography bump | PR 1 | `pnpm vitest run components/__tests__/AIAgentConsole.test.tsx hooks/useChatPreferences.test.ts hooks/useResizableHandle.test.ts` | N/A — DevTools visual smoke (handle, drawer, reload) | Revert W2 restores `w-96` + old typography; hooks from W1 stay inert. |
| W3 | Cap (lint + format + full suite) | PR 1 | `pnpm vitest run` | N/A — verification only | Revert W3 = amend prior commits if cleanup landed. |

## Work-Unit W1: Hooks Land First (RED → GREEN)

### Task W1.1: RED — write `useChatPreferences` failing tests
- **Type**: RED
- **Work-unit**: W1
- **Files**: `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/__tests__/useChatPreferences.test.ts`
- **Spec**: REQ-APL-002, REQ-APL-006
- **Verify**: `cd /private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend && pnpm vitest run hooks/__tests__/useChatPreferences.test.ts` → module-not-found error.
- **Status**: complete
- Cases: empty localStorage defaults to 480; stored `"600"` restores; invalid `"-1"`/`"9999"`/`"abc"` falls back to 480; debounced write 250 ms after `setWidth(540)`; unmount clears pending timer; `fontScale === 1` default; `setFontScale` is a function.

### Task W1.2: RED — write `useResizableHandle` failing tests
- **Type**: RED
- **Work-unit**: W1
- **Files**: `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/__tests__/useResizableHandle.test.ts`
- **Spec**: REQ-APL-001, REQ-APL-003
- **Verify**: `cd /private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend && pnpm vitest run hooks/__tests__/useResizableHandle.test.ts` → module-not-found error.
- **Status**: complete
- Cases: `pointermove` from `clientX=0` to `clientX=1000` clamps `setWidth` to 720; `pointerdown` adds window listeners and `pointerup` removes both; non-handle target is no-op.

### Task W1.3: GREEN — implement `useChatPreferences`
- **Type**: GREEN
- **Work-unit**: W1
- **Files**: `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/useChatPreferences.ts`
- **Spec**: REQ-APL-002, REQ-APL-006
- **Verify**: `cd /private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend && pnpm vitest run hooks/__tests__/useChatPreferences.test.ts` → all 7 green.
- **Status**: complete
- Export `MIN_WIDTH=320`, `MAX_WIDTH=720`, `DEFAULT_WIDTH=480`, `DEFAULT_FONT_SCALE=1`, `STORAGE_KEY_WIDTH="nexgen.aiChat.width"`, `DEBOUNCE_MS=250`; useEffect reads storage with `try/catch`; `setWidth` clamps + debounced write; cleanup clears timer; `fontScale`/`setFontScale` exposed, dormant.

### Task W1.4: GREEN — implement `useResizableHandle`
- **Type**: GREEN
- **Work-unit**: W1
- **Files**: `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/useResizableHandle.ts`
- **Spec**: REQ-APL-001, REQ-APL-003
- **Verify**: `cd /private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend && pnpm vitest run hooks/__tests__/useResizableHandle.test.ts` → all 3 green.
- **Status**: complete
- Returns `{ onPointerDown, onDoubleClick }`; `onPointerDown` registers window `pointermove`/`pointerup` (capture), `pointermove` clamps `startW + (clientX-startX)` into setWidth, `pointerup` detaches; unmount effect detaches if drag still active; `onDoubleClick` calls `setWidth(480)`.

### Task W1.5: VERIFY — full hook suite + lint pass for W1
- **Type**: VERIFY
- **Work-unit**: W1
- **Files**: `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/useChatPreferences.ts`, `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/useResizableHandle.ts`, `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/__tests__/useChatPreferences.test.ts`, `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/__tests__/useResizableHandle.test.ts`
- **Spec**: REQ-APL-001..006 (hook layer)
- **Verify**: `cd /private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend && pnpm vitest run hooks/__tests__/useChatPreferences.test.ts hooks/__tests__/useResizableHandle.test.ts` → 10/10 green.
- **Status**: complete

## Work-Unit W2: Integrate + Typography Bump

### Task W2.1: GREEN — wire `App.tsx` (dynamic width + handle + drawer)
- **Type**: GREEN
- **Work-unit**: W2
- **Files**: `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/App.tsx`
- **Spec**: REQ-APL-001, REQ-APL-002, REQ-APL-003, REQ-APL-004
- **Verify**: `cd /private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend && pnpm vitest run hooks/__tests__/useChatPreferences.test.ts hooks/__tests__/useResizableHandle.test.ts` → 10/10 still green; manual: aside renders drag handle at left, drag clamps 320-720, dblclick resets to 480, resize below 768 px → full-width drawer.
- **Status**: complete
- Replace `w-96` with `style={{ width: chatWidth }}`; import hooks; add `isOverlay` state + debounced `resize` listener; conditionally render `<div data-testid="ai-chat-resize-handle" role="separator" aria-orientation="vertical">` only when `!isOverlay`.

### Task W2.2: GREEN — bump typography in `AIAgentConsole.tsx`
- **Type**: GREEN
- **Work-unit**: W2
- **Files**: `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/components/AIAgentConsole.tsx`
- **Spec**: REQ-APL-005
- **Verify**: `cd /private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend && grep -nE "text-base|text-sm" components/AIAgentConsole.tsx` → lines 92, 111, 140 show `text-sm`, `text-base`, `text-base` respectively; `text-[10px]` chrome untouched.
- **Status**: complete
- L92 `text-xs` → `text-sm` (header label); L111 `text-sm` → `text-base` (message bubble); L140 `text-sm` → `text-base` (input).

### Task W2.3: GREEN — update `AIAgentConsole.test.tsx` assertions + add 3 cases
- **Type**: GREEN
- **Work-unit**: W2
- **Files**: `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/components/__tests__/AIAgentConsole.test.tsx`
- **Spec**: REQ-APL-005
- **Verify**: `cd /private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend && pnpm vitest run components/__tests__/AIAgentConsole.test.tsx` → all green.
- **Status**: complete
- Refresh existing selectors that asserted `text-xs`/`text-sm` on message+header+input; add 3 assertions: header `text-sm`, message bubble `text-base`, input `text-base`.

### Task W2.4: VERIFY — hooks + component suite green together
- **Type**: VERIFY
- **Work-unit**: W2
- **Files**: `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/__tests__/useChatPreferences.test.ts`, `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/__tests__/useResizableHandle.test.ts`, `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/components/__tests__/AIAgentConsole.test.tsx`
- **Spec**: REQ-APL-001..006 (component + hook layer)
- **Verify**: `cd /private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend && pnpm vitest run components/__tests__/AIAgentConsole.test.tsx hooks/__tests__/useChatPreferences.test.ts hooks/__tests__/useResizableHandle.test.ts` → all green.
- **Status**: complete

## Work-Unit W3: Cap (Lint + Format + Full Suite)

### Task W3.1: LINT — clean on every touched file
- **Type**: CONFIG
- **Work-unit**: W3
- **Files**: `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/useChatPreferences.ts`, `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/useResizableHandle.ts`, `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/components/AIAgentConsole.tsx`, `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/App.tsx`, `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/components/__tests__/AIAgentConsole.test.tsx`, `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/__tests__/useChatPreferences.test.ts`, `/private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend/hooks/__tests__/useResizableHandle.test.ts`
- **Spec**: N/A
- **Verify**: `cd /private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend && pnpm run lint -- hooks/useChatPreferences.ts hooks/useResizableHandle.ts components/AIAgentConsole.tsx App.tsx components/__tests__/AIAgentConsole.test.tsx hooks/__tests__/useChatPreferences.test.ts hooks/__tests__/useResizableHandle.test.ts` → exit 0.
- **Status**: complete

### Task W3.2: FORMAT — Prettier clean on every touched file
- **Type**: CONFIG
- **Work-unit**: W3
- **Files**: same seven files as W3.1
- **Spec**: N/A
- **Verify**: `cd /private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend && pnpm run format:check -- <same files>` → exit 0; if not, run `pnpm run format -- <same files>` then re-check.
- **Status**: complete

### Task W3.3: VERIFY — full frontend Vitest suite green
- **Type**: VERIFY
- **Work-unit**: W3
- **Files**: all `frontend/**/*.test.{ts,tsx}`
- **Spec**: REQ-APL-001..006
- **Verify**: `cd /private/tmp/next-gen-main-check/.worktrees/feat-461-ai-chat-resizable/frontend && pnpm vitest run` → all green.
- **Status**: complete

## Summary

- **Total tasks**: 12 (W1: 5, W2: 4, W3: 3).
- **Estimated LOC**: 250-350 (under 800 budget).
- **Per-commit LOC**: W1 ≤ 200, W2 ≤ 200, W3 ≤ 50.
- **Review effort**: 1 PR, 3 commits.
- **Risk**: low — Vitest + React 19 stable, manual pointer handler well-understood, no new deps.
