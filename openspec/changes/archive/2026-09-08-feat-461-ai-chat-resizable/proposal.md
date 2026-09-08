# Proposal: feat(ai-chat): make AI chat panel resizable (drag width) and increase base font size

Issue: #461
Change: `feat-461-ai-chat-resizable`
Branch: `feat/461-ai-chat-resizable` (from `main` @ `177eb39`, which includes PR #463 / #457 retention policy).

## Intent

The AI chat panel is mounted in a fixed-width `<aside className="w-96">` (`≈ 384px`) in `frontend/App.tsx` (~line 253-257). Operators cannot resize it on the fly, so on wide monitors the chat wastes horizontal real estate and on narrow laptops it forces horizontal scroll inside the message list. Message body text uses `text-sm` (14px) and the header/buttons use `text-xs` (12px), which is too small for sustained operator use and risks eye strain / misreads as more content (event lists, CI names, IPs) is added.

This change makes the panel user-resizable (drag the left edge, clamp 320-720px, persist width in `localStorage`, double-click to reset to 480px, full-width drawer below 768px) and bumps the in-panel typography one step (`text-sm` -> `text-base` for messages and input; `text-xs` -> `text-sm` in the header). It introduces a `useChatPreferences()` hook so the same source of truth can later host a per-user font scale without re-plumbing the layout.

## Scope

### In Scope
- Replace the fixed `w-96` wrapper in `frontend/App.tsx` with a dynamic `style={{ width: chatWidth }}` driven by `useChatPreferences()`.
- Add a 6px drag handle on the left edge of the aside (`cursor: col-resize`) with `pointerdown` + window `pointermove` / `pointerup` listeners, clamped to `[320, 720]`.
- Persist width to `localStorage` under `nexgen.aiChat.width` (read on mount, write debounced on `pointerup`).
- Double-click the handle to reset width to the default 480px and persist.
- Responsive fallback: when `window.innerWidth < 768`, render the aside as a full-width overlay drawer (existing show/hide `translate-x-full` behavior is reused).
- Typography bump inside `AIAgentConsole.tsx`: message bubbles and input `text-sm` -> `text-base`; header label `text-xs` -> `text-sm`; footer stays `text-[10px]` mono (chrome, not user-facing message content).
- New `frontend/hooks/useChatPreferences.ts` exposing `{ width, setWidth, fontScale, setFontScale }` with `fontScale` defaulted to 1 and not yet wired to any UI.
- Update `frontend/components/__tests__/AIAgentConsole.test.tsx`: refresh selectors / class assertions for new font sizes, add tests for drag, persistence, dblclick reset, and responsive fallback.

### Out of Scope
- AI chat backend changes (issues #458, #460).
- Introducing `react-resizable-panels` or any new runtime dependency.
- App-wide font scale / accessibility settings (only the hook is in place; UI lands later).
- Touching `SystemDashboard`, `MonitoringConsole`, or any other route component that happens to mount `<AIAgentConsole />`.
- Backend, Neo4j, Timescale, or API surface changes.

## Capabilities

> Contract for `sdd-spec`: this change adds one new frontend capability and does not modify any existing spec-level behavior (no backend requirement is touched).

### New Capabilities
- `ai-chat-panel-layout`: layout, persistence, and responsive behavior of the operator-facing AI chat panel rendered inside `App.tsx`'s `<aside>`. Covers drag handle, width clamp, localStorage persistence, double-click reset, < 768px drawer fallback, and base font sizing.

### Modified Capabilities
- None. (No requirement in `openspec/specs/*` describes the AI chat panel layout today; this is purely additive UI behavior.)

## Approach

1. **Width source of truth.** Create `frontend/hooks/useChatPreferences.ts`. It reads `localStorage.getItem('nexgen.aiChat.width')` once on mount, falls back to 384, clamps to `[320, 720]`, and returns `{ width, setWidth, fontScale, setFontScale }`. The setter writes to localStorage on a debounced (≤ 250 ms) `pointerup` boundary.
2. **Dynamic aside width.** In `frontend/App.tsx`, replace `w-96` with `style={{ width: chatWidth }}` and keep the existing `transition-all duration-500` for show/hide. The aside still owns `showAIAgent` visibility.
3. **Drag handle.** Render an absolutely positioned `<div>` at `left: 0; top: 0; bottom: 0; width: 6px; cursor: col-resize;` inside the aside. `pointerdown` registers window-level `pointermove` / `pointerup` listeners; each `pointermove` computes `next = clamp(width + deltaX, 320, 720)` and calls `setWidth(next)` synchronously (no localStorage write per move). `pointerup` persists via the debounced setter and detaches listeners.
4. **Double-click reset.** The same handle listens for `dblclick` -> `setWidth(480)` and persists.
5. **Responsive fallback.** On mount and on `window.resize`, if `innerWidth < 768` the aside renders `position: fixed; inset: 0; width: 100vw; z-index: 50` (full-width drawer) instead of the resizable sidebar. Drag is disabled in this mode.
6. **Font bump.** Inside `AIAgentConsole.tsx` change: `text-sm` -> `text-base` on the message bubble container (line 111) and on the `<input>` (line 140); `text-xs` -> `text-sm` on the header label `<span>` (line 92). Leave the `text-[10px]` model label and the loading-bounce dots untouched (chrome density).
7. **Hook future-proofing.** The same `useChatPreferences()` hook owns `fontScale` (default 1). The current PR does not multiply styles by `fontScale`; the hook is in place so the eventual font-scale UI is a one-line consumer, not a refactor.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `frontend/hooks/useChatPreferences.ts` | New | Single source of truth for `{ width, setWidth, fontScale, setFontScale }`; localStorage read on mount, debounced write, clamp `[320, 720]`. |
| `frontend/App.tsx` (≈ line 253-257) | Modified | `<aside>` swap from `w-96` to dynamic `style={{ width }}`; mount drag handle; responsive < 768px drawer. |
| `frontend/components/AIAgentConsole.tsx` | Modified | Typography bump: message bubbles + input `text-sm` -> `text-base`; header label `text-xs` -> `text-sm`; chrome (`text-[10px]`, loading dots) untouched. |
| `frontend/components/__tests__/AIAgentConsole.test.tsx` | Modified | Refresh class assertions; add new tests for drag delta, localStorage persistence, dblclick reset, responsive drawer fallback. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Drag handle leaks listeners (no detach on unmount) causing setState-after-unmount warnings. | Med | Attach listeners inside the same `pointerdown` handler, detach in `pointerup` and in a component-level `useEffect` cleanup. |
| localStorage read on SSR / first paint mismatches between server and client and causes hydration warnings. | Low | This is a Vite SPA (no SSR), but the read is still done inside `useEffect` to avoid the first render returning 0 / NaN. |
| Responsive fallback uses `window.innerWidth` directly and does not update during rotation / devtools drag. | Med | Add a `resize` listener (debounced ~120 ms) that re-evaluates drawer vs. sidebar mode; covered by a follow-up note in `Out of Scope` for React-19 viewport hooks. |
| `text-base` increase pushes input height past 44px and breaks dense message list scrolling math. | Low | Single-line change; existing `flex-1` on the scroll container absorbs it. If visual regression is reported, the hook's `fontScale` is already in place to offset. |
| Existing snapshots / DOM assertions in `AIAgentConsole.test.tsx` start failing on font class changes. | High | Test updates are explicitly listed under `Affected Areas` and required by the acceptance criteria; no external snapshot files (no Playwright goldens) reference these classes. |

## Rollback Plan

Revert the single PR. Because the change is fully contained to `frontend/` (no backend, no new dep, no migration, no persisted data beyond `localStorage`), `git revert` of the merge commit restores the prior `w-96` aside and `text-sm` typography. `localStorage` keys written by this change (`nexgen.aiChat.width`, optionally `nexgen.aiChat.fontScale`) are inert after revert — operators who reload simply fall back to the 384px default, matching pre-change behavior. No data migration, no backwards-compat shim needed.

## Dependencies

- None. No new runtime dependency. No backend coupling. Reuses existing `useState` / `useEffect` from React 19.2 and existing localStorage access (already used by other frontend code in the same package).

## Success Criteria

Maps 1:1 to the acceptance criteria in issue #461.

- [ ] Operator can drag the left edge of the panel to widen or narrow it; clamp `[320, 720]px` enforced.
- [ ] Width persists across full page reloads via `localStorage` key `nexgen.aiChat.width`.
- [ ] Double-click the handle resets width to the default (480px) and persists.
- [ ] Below 768px viewport, the panel becomes a full-width overlay drawer (not a narrow sidebar).
- [ ] Message body and input font are at least `text-base` (16px); no `text-xs` remains in user-facing message / header / input areas (the `text-[10px]` model footer is exempt as chrome).
- [ ] `frontend/components/__tests__/AIAgentConsole.test.tsx` snapshots and assertions updated; full frontend test suite (`cd frontend && corepack pnpm test:run`) green.
- [ ] No regressions on `SystemDashboard` or `MonitoringConsole` routes that include the chat.

## Notes / Trade-offs

- **Manual pointer handler vs. library.** Splitter libraries such as `react-resizable-panels` exist, but adding a runtime dep for one 6px handle is not worth the bundle / maintenance cost in this slice. A ~40-line custom hook keeps the change self-contained.
- **`window.innerWidth` vs. viewport hook.** Direct `window.innerWidth` is the lowest-friction check for the < 768px drawer. If a future slice needs SSR-safe or `useSyncExternalStore`-based viewport tracking, that is a follow-up — explicitly tracked in `Out of Scope` for the AI chat backend issues (#458, #460).
- **Font scale hook is dormant.** `useChatPreferences().fontScale` is reserved API surface only; the current slice does not multiply styles by it. The acceptance criterion forbids shipping the UI yet, so reviewers will see the field with default `1` and no consumer — that is intentional.
