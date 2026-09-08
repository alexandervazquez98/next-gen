# Design: AI Chat Panel Resizable + Typography Bump

> Change: `feat-461-ai-chat-resizable` · Issue: #461 · Branch: `feat/461-ai-chat-resizable`
> Inputs: [proposal](../proposal.md) · [delta spec](../specs/ai-chat-panel-layout/spec.md) · [canonical spec](../../../../openspec/specs/ai-chat-panel-layout/spec.md)
> Stack: React 19.2.3 · TypeScript 5.8 · Vitest 4.1 · jsdom · Tailwind 4

## Technical Approach

Introduce a single source of truth for chat panel layout state via a new `useChatPreferences()` hook. The hook owns `{ width, fontScale }` and the `localStorage['nexgen.aiChat.width']` write-through. `App.tsx`'s `<aside>` swaps its fixed `w-96` for a dynamic `style={{ width }}` and renders a 6px drag handle (`cursor: col-resize`) at `left: 0`. Drag math runs through a focused companion hook (`useResizableHandle`) so it is unit-testable without DOM mounting. A debounced `resize` listener flips the aside into full-width drawer mode below 768px. Inside `AIAgentConsole.tsx` the in-panel typography is bumped one step (`text-sm → text-base` for messages and input, `text-xs → text-sm` for the header). No new runtime dependency; no backend touched. Requirements REQ-APL-001..006 are the contract surface; every acceptance criterion maps to a named Vitest case below.

## Architecture Decisions

### Decision: Single hook + companion drag hook (not inline pointer math)

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Inline pointer math in `App.tsx` | Zero new files; no test surface beyond mounting `App`. | Reject — untestable without a full router/auth render. |
| One hook `useChatPreferences` doing both state and drag | Fewer files; but mixes localStorage I/O with pointer event plumbing. | Reject — drags in `useChatPreferences`'s contract surface. |
| Two hooks: `useChatPreferences` (state) + `useResizableHandle` (drag math) | Clean separation, `useResizableHandle` is a pure function of `pointermove` deltas, testable with raw events. | **Choose.** Matches project convention of one hook per file under `frontend/hooks/`. |

### Decision: Co-locate tests with source (matches existing pattern)

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `frontend/hooks/__tests__/useChatPreferences.test.ts` (task brief) | Cleaner URL per test; one folder to `.gitignore`. | Reject — no other hook in the repo uses a `__tests__/` subdir. |
| `frontend/hooks/useChatPreferences.test.ts` next to source | Matches `useEventCorrelation.test.ts`, `useMapClustering.test.ts`. | **Choose.** Consistency with the existing two hook tests beats the brief's preference. |

### Decision: Custom pointer handler instead of `react-resizable-panels`

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `react-resizable-panels` | Battle-tested; bundle cost + license review + a new dep for one 6px handle. | Reject — out of scope per proposal; bundle + maintenance overhead unjustified. |
| Custom `pointerdown/move/up` (~40 LOC) | Self-contained, zero deps, easy to test. | **Choose.** Total drag surface fits in one hook. |

### Decision: localStorage read inside `useEffect`, not at module load

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Read at module load (sync) | Faster first paint, but SSR-unsafe and breaks in jsdom tests. | Reject. |
| Read in `useState` initializer | Synchronous, but fires before React commits; can desync with StrictMode double-invoke. | Reject. |
| Read in `useEffect` (post-mount) | Triggers one re-render after mount; correct, testable, idempotent. | **Choose.** Same pattern as `useSmartCulling`. |

### Decision: Debounce localStorage writes (250 ms) on `setWidth`

Synchronous writes per pointer-move would hammer the storage layer on a single 600px drag (~50 events). The spec mandates a debounced write at 250 ms (`REQ-APL-002`). The debounce timer lives in a `useRef<NodeJS.Timeout | null>` inside `useChatPreferences`; the setter cancels the previous timer and schedules a fresh one. On unmount, the cleanup effect clears any pending timer.

### Decision: Responsive fallback via `window.innerWidth` + debounced `resize`

The spec (`REQ-APL-004`) calls for a resize listener debounced at 250 ms. A `useEffect` inside `App.tsx` registers the listener on mount, debounces via the same `useRef<NodeJS.Timeout>` pattern, and clears on cleanup. Below 768 px the aside becomes `position: fixed; inset: 0; width: 100vw; z-index: 50` and the drag handle is not rendered.

### Decision: `fontScale` is reserved API surface, not wired in this change

`REQ-APL-006` requires the hook to expose `fontScale` and `setFontScale`, default `1`. This change MUST NOT multiply any style by `fontScale`. Future slices consume it; the dormant field exists so that future work is a one-line wiring, not a refactor.

## Data Flow

    Mount ─────────────────────────────────────────────────────────────
       │
       ▼
    useChatPreferences()
       │  (useEffect on mount)
       ├──► localStorage.getItem("nexgen.aiChat.width")
       │       ├─ valid (finite, [320, 720]) → setWidth(stored)
       │       └─ missing / invalid        → setWidth(DEFAULT_WIDTH = 480)
       │
       └──► returns { width, setWidth, fontScale, setFontScale }

    Drag (sidebar mode only, viewport ≥ 768px) ─────────────────────────
       │
       ▼
    <div handle onPointerDown>
       │  e.preventDefault(); capturePointer
       │
       ▼
    window pointermove ─► useResizableHandle({startX, startW}, setWidth)
       │                       └─ next = clamp(startW + (e.clientX - startX),
       │                                       MIN_WIDTH, MAX_WIDTH)
       │                       └─ setWidth(next)  (state-only; no localStorage)
       │
       ▼
    window pointerup ─► detach listeners; debounced write fires within 250ms

    Resize ────────────────────────────────────────────────────────────
       │
       ▼
    window resize (debounced 250ms)
       │  innerWidth < 768  → isOverlay = true   (full-width drawer, no handle)
       │  innerWidth ≥ 768  → isOverlay = false  (sidebar + handle)
       │
       ▼
    Re-render <aside style={{ width: isOverlay ? "100%" : chatWidth }}>

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/hooks/useChatPreferences.ts` | Create | `{ width, setWidth, fontScale, setFontScale }` hook; localStorage I/O; clamp `[320, 720]`; 250 ms debounced write; SSR-safe. |
| `frontend/hooks/useChatPreferences.test.ts` | Create | Vitest cases for mount default, localStorage round-trip, clamp behavior, invalid stored values, debounced write, `fontScale` exposure. |
| `frontend/hooks/useResizableHandle.ts` | Create | `useResizableHandle(setWidth, options?)`; pointer event plumbing; clamp helper. Returns `{ onPointerDown }` only — no DOM it owns. |
| `frontend/hooks/useResizableHandle.test.ts` | Create | Vitest cases for clamp on `pointermove`, listener detach on `pointerup`, no-op when target is not handle. |
| `frontend/App.tsx` | Modify | Replace `w-96` with `style={{ width: chatWidth }}` (line 253-257 region); inject `<div>` drag handle; add debounced `resize` listener; conditional render of handle when not overlay. |
| `frontend/components/AIAgentConsole.tsx` | Modify | Header `<span>` (line 92): `text-xs → text-sm`. Message bubble `<div>` (line 111): `text-sm → text-base`. Input (line 140): `text-sm → text-base`. Chrome (`text-[10px]`, loading dots) untouched. |
| `frontend/components/__tests__/AIAgentConsole.test.tsx` | Modify | Add three assertions for new typography classes; no behavioral test changes (chat behavior is unchanged). |

## Interfaces / Contracts

### `useChatPreferences`

```ts
// frontend/hooks/useChatPreferences.ts
export interface UseChatPreferencesReturn {
  width: number;                // current panel width, px
  setWidth: (w: number) => void; // clamped, debounced localStorage write
  fontScale: number;             // dormant; always 1 in this change
  setFontScale: (s: number) => void; // dormant; state-only, no localStorage
}

export function useChatPreferences(): UseChatPreferencesReturn;

// Constants (module-private; re-exported for tests):
export const MIN_WIDTH = 320;
export const MAX_WIDTH = 720;
export const DEFAULT_WIDTH = 480;
export const DEFAULT_FONT_SCALE = 1;
export const STORAGE_KEY_WIDTH = "nexgen.aiChat.width";
export const DEBOUNCE_MS = 250;
```

**Clamp rule** (single source): `clampWidth(n) = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, n))`. Applied on read (stored value) and on every `setWidth` call. Invalid stored value (`NaN`, `<= 0`, `> MAX_WIDTH`) → `DEFAULT_WIDTH`.

**localStorage contract**:
- Read on mount only (single `useEffect`).
- Write debounced 250 ms after last `setWidth` call. Stored as the stringified integer pixel value (e.g. `"540"`).
- Errors wrapped in `try/catch` — falls back to `DEFAULT_WIDTH`; never throws.

### `useResizableHandle`

```ts
// frontend/hooks/useResizableHandle.ts
export interface UseResizableHandleOptions {
  minWidth?: number;   // default MIN_WIDTH (320)
  maxWidth?: number;   // default MAX_WIDTH (720)
}

export interface ResizableHandleBindings {
  onPointerDown: (e: React.PointerEvent<HTMLElement>) => void;
  onDoubleClick: (e: React.MouseEvent<HTMLElement>) => void;
}

export function useResizableHandle(
  setWidth: (w: number) => void,
  options?: UseResizableHandleOptions
): ResizableHandleBindings;
```

**Behavior**:
- `onPointerDown`: `e.preventDefault()` (prevents text selection), store `startX = e.clientX` and `startW = current width` in a `useRef`, attach window-level `pointermove` / `pointerup` (captured).
- `onPointerMove` (window listener): `next = clamp(startW + (e.clientX - startX), MIN, MAX)`; `setWidth(next)` — state only, no localStorage.
- `onPointerUp` (window listener): detach both listeners; `setWidth(current)` triggers the debounced persist.
- `onDoubleClick`: `setWidth(DEFAULT_WIDTH)` immediately (still debounced-persists via hook).
- Cleanup: a component-level `useEffect` returns a teardown that removes both listeners if the component unmounts mid-drag.

### `App.tsx` integration (additions only)

```tsx
import { useChatPreferences } from "./hooks/useChatPreferences";
import { useResizableHandle } from "./hooks/useResizableHandle";

// inside MainLayout:
const { width: chatWidth, setWidth } = useChatPreferences();
const { onPointerDown: onHandlePointerDown, onDoubleClick: onHandleDblClick } =
  useResizableHandle(setWidth);

const [isOverlay, setIsOverlay] = useState<boolean>(
  typeof window !== "undefined" && window.innerWidth < 768
);
useEffect(() => {
  const t = { current: null as NodeJS.Timeout | null };
  const onResize = () => {
    if (t.current) clearTimeout(t.current);
    t.current = setTimeout(() => setIsOverlay(window.innerWidth < 768), 250);
  };
  window.addEventListener("resize", onResize);
  return () => {
    window.removeEventListener("resize", onResize);
    if (t.current) clearTimeout(t.current);
  };
}, []);

// aside swap:
<aside
  className={`border-l border-white/5 glass flex flex-col transition-all duration-500 ${
    isEditing || !showAIAgent
      ? "opacity-0 translate-x-full absolute right-0"
      : "relative opacity-100 translate-x-0"
  } ${isOverlay ? "fixed inset-0 w-screen z-50" : ""}`}
  style={{ width: isOverlay ? "100%" : chatWidth }}
>
  {!isOverlay && (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize chat panel"
      data-testid="ai-chat-resize-handle"
      onPointerDown={onHandlePointerDown}
      onDoubleClick={onHandleDblClick}
      className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-brand-500/30 transition-colors"
    />
  )}
  <AIAgentConsole />
</aside>
```

### `AIAgentConsole.tsx` line-level edits

| Line | Before | After | Why |
|------|--------|-------|-----|
| 92 | `text-xs font-black uppercase tracking-widest text-white` | `text-sm font-black uppercase tracking-widest text-white` | REQ-APL-005: header ≥ 14 px |
| 111 | `... rounded-2xl text-sm leading-relaxed ...` | `... rounded-2xl text-base leading-relaxed ...` | REQ-APL-005: message bubble ≥ 16 px |
| 140 | `... py-3 pl-4 pr-12 text-sm text-white ...` | `... py-3 pl-4 pr-12 text-base text-white ...` | REQ-APL-005: input/placeholder ≥ 16 px |

`text-[10px]` (line 96 model label) and the loading-bounce dots (lines 124-126) are chrome — exempt per the proposal.

## Testing Strategy

| Layer | What | Approach | Files |
|-------|------|----------|-------|
| Unit (hook) | Default width on empty localStorage | `renderHook` + assert `result.current.width === 480` | `useChatPreferences.test.ts` |
| Unit (hook) | Stored width restored | `localStorage.setItem(KEY, "600")` before render; assert `=== 600` | `useChatPreferences.test.ts` |
| Unit (hook) | Clamp lower / upper / NaN / negative | seed each invalid value, assert `=== 480` | `useChatPreferences.test.ts` |
| Unit (hook) | Debounced write | call `setWidth(540)`, `vi.advanceTimersByTime(250)`, assert `localStorage.getItem(KEY) === "540"` | `useChatPreferences.test.ts` |
| Unit (hook) | Unmount clears pending timer | call `setWidth`, unmount before debounce fires, advance timers, assert no write | `useChatPreferences.test.ts` |
| Unit (hook) | `fontScale` exposure | assert `result.current.fontScale === 1` and `setFontScale` is a function | `useChatPreferences.test.ts` |
| Unit (hook) | Drag clamp | call `onPointerDown({ clientX: 0 })`, fire `pointermove` on `window` with `{ clientX: 1000 }`, assert `setWidth` called with `720` | `useResizableHandle.test.ts` |
| Unit (hook) | Listener detach on `pointerup` | spy on `window.add/removeEventListener`; assert pair added on `pointerdown`, removed on `pointerup` | `useResizableHandle.test.ts` |
| Unit (hook) | Double-click resets | fire `dblclick` on the handle, assert `setWidth(480)` | `useResizableHandle.test.ts` |
| Component | Header has `text-sm` | `render(<AIAgentConsole />)`, query `getByText(/NEX-GEN Reasoning/i)`, assert `classList.contains("text-sm")` | `AIAgentConsole.test.tsx` (new) |
| Component | Message bubble has `text-base` | send a message, assert bubble `classList.contains("text-base")` | `AIAgentConsole.test.tsx` (new) |
| Component | Input has `text-base` | `getByPlaceholderText(/Describe action/i)`, assert class | `AIAgentConsole.test.tsx` (new) |

**Test commands** (Vitest 4.1 + jsdom):

```bash
# Unit + new component cases
cd frontend && corepack pnpm test:run -- hooks/useChatPreferences.test.ts hooks/useResizableHandle.test.ts components/__tests__/AIAgentConsole.test.tsx

# Lint
cd frontend && pnpm run lint -- hooks/useChatPreferences.ts hooks/useResizableHandle.ts components/AIAgentConsole.tsx App.tsx components/__tests__/AIAgentConsole.test.tsx hooks/useChatPreferences.test.ts hooks/useResizableHandle.test.ts

# Format check
cd frontend && pnpm run format:check -- hooks/useChatPreferences.ts hooks/useResizableHandle.ts components/AIAgentConsole.tsx App.tsx components/__tests__/AIAgentConsole.test.tsx hooks/useChatPreferences.test.ts hooks/useResizableHandle.test.ts
```

The hook tests use `renderHook` from `@testing-library/react` (already a dev dep, v16.3.2). Pointer event tests use raw `fireEvent.pointerDown/Move/Up` from `@testing-library/react` — no need for `@testing-library/user-event` v14 semantics for this scope. Fake timers via `vi.useFakeTimers()` for the debounce test only.

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary is touched. The change is bounded to React DOM event handlers and `localStorage` reads/writes within an existing authenticated SPA route.

## Work-Unit Commit Plan

Three commits, each ≤ 250 LOC, each independently buildable + green, each a candidate standalone PR if the change is later chained.

### W1 — Hooks land first (RED → GREEN)

**Files**: `frontend/hooks/useChatPreferences.ts`, `frontend/hooks/useResizableHandle.ts`, `frontend/hooks/useChatPreferences.test.ts`, `frontend/hooks/useResizableHandle.test.ts`.

**Sequence**:
1. Write all hook tests (RED).
2. Implement `useChatPreferences` until green.
3. Implement `useResizableHandle` until green.

**Verification**: `corepack pnpm test:run -- hooks/useChatPreferences.test.ts hooks/useResizableHandle.test.ts` passes; `pnpm run lint` clean on the four files.

**Rollback boundary**: Revert W1 alone leaves `App.tsx` unchanged — chat works as before (no resize, default width via existing `w-96`). localStorage is untouched.

**Commit message**: `feat(ai-chat): add useChatPreferences + useResizableHandle hooks with persistence`.

### W2 — Integration + typography bump

**Files**: `frontend/App.tsx` (modify aside + handle + resize listener), `frontend/components/AIAgentConsole.tsx` (3 typography classes), `frontend/components/__tests__/AIAgentConsole.test.tsx` (3 new assertions).

**Sequence**:
1. Apply the three typography edits to `AIAgentConsole.tsx`.
2. Add the three new test assertions to `AIAgentConsole.test.tsx`.
3. Wire `App.tsx`: import hooks, swap `aside` style, add handle `div`, add resize `useEffect`.

**Verification**: full frontend test suite green; visual smoke of `<aside>` shows drag handle on the left edge; resizing below 768 px in DevTools switches to drawer; reload restores last width.

**Rollback boundary**: Revert W2 restores `w-96`, old typography, no handle. Hook files from W1 stay (orphan but inert; cleanup deferred to W3 if reverted together).

**Commit message**: `feat(ai-chat): wire resizable drag handle, drawer fallback, and base font bump`.

### W3 — Cap + verify

**Files**: none new. Optional small cleanup if reviewer requests.

**Verification**: full `corepack pnpm test:run` green; `pnpm run lint` exits 0 with `--max-warnings=100`; `pnpm run format:check` clean on every touched file; manual smoke covers the success criteria checklist from the proposal.

**Rollback boundary**: This is a verification commit; revert by amending prior commits if any cleanup lands.

**Commit message**: `chore(ai-chat): cap verify pass for #461`.

### Size sanity

Counted authored additions+deletions across W1+W2+W3: ~250 LOC (two ~50-LOC hooks + two ~120-LOC test files + ~30 LOC of `App.tsx` + three 1-token class edits + 3 assertions). Comfortably under the 400-line review budget and the 800-line session budget.

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `localStorage` throws (Safari private mode, quota) | Med | Wrap reads/writes in `try/catch` inside `useChatPreferences`; fall back to `DEFAULT_WIDTH`. Tests cover a `vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); })` case. |
| Drag handle leaked listeners fire `setState` after unmount | Med | Companion hook attaches listeners inside `onPointerDown` and detaches on `pointerup`; a component-level `useEffect` cleanup also detaches for unmount-mid-drag. |
| Drag triggers text selection on accidental drag | Low | `e.preventDefault()` on `pointerdown`; only the 6 px handle (`w-1.5`) initiates drag, not the message body. |
| Rapid viewport rotation / devtools resize storm | Low | Debounced `resize` listener (250 ms); single boolean state update per debounce window. |
| Vitest jsdom does not fully simulate `pointermove` capture | Low | Use `fireEvent.pointerDown/Move/Up` from `@testing-library/react` on the handle element + window listener; write a RED test first to confirm jsdom dispatches them (one already exists in the spec matrix). |
| Stale `nexgen.aiChat.width` value persists after rollback | Low | On the next mount after rollback the value is ignored (the reverted code never reads it). No user-visible artifact. No cleanup needed. |

## Migration / Rollout

No data migration. No feature flag. No backend rollout. Frontend-only: Vite SPA hot-reloads on next page load. localStorage write happens only after a user actively drags the new handle, so existing users see the legacy `w-96` width on first load and only diverge once they drag. A subsequent revert restores `w-96` and ignores any persisted value — no migration shim needed.

## Open Questions

- None. All blocking decisions (clamp range, default width, debounce ms, breakpoint, storage key) are fixed by the spec. The dormant `fontScale` is intentionally non-decision per `REQ-APL-006`.
