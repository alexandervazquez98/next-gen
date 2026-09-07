# AI Chat Panel Layout — Specification

## Purpose

The operator-facing AI chat panel must adapt to different monitors, reading distances, and viewport sizes. This capability owns the panel's width source of truth, drag-to-resize handle, localStorage persistence, double-click reset, responsive drawer fallback, base font sizing, and the `useChatPreferences()` hook that backs all of it.

## Requirements

### Requirement: REQ-APL-001 — Panel is horizontally resizable via a drag handle

The AI chat panel MUST be horizontally resizable by the operator via a drag handle on its left edge. The handle MUST be a `<div>` at `left: 0` with width 6px and `cursor: col-resize`, accepting both mouse and touch via `pointerdown`. Width MUST update in real time during drag (not only on release) via React state, and MUST be clamped to the inclusive range `[320, 720]` pixels for the entire drag.

#### Scenario: Drag handle is present and clickable

- GIVEN the AI chat panel is mounted
- WHEN the operator inspects its left edge
- THEN a 6px handle MUST be visible at `left: 0` with `cursor: col-resize`
- AND it MUST respond to `pointerdown` for mouse and touch.

#### Scenario: Drag updates width in real time within clamp range

- GIVEN the panel width is currently 480px
- WHEN the operator drags the handle right by 100px
- THEN the width MUST update to 580px before `pointerup`
- AND the layout MUST reflect the new width without waiting for release.

#### Scenario: Drag is clamped to the upper bound

- GIVEN the panel width is currently 720px
- WHEN the operator drags further right
- THEN the width MUST remain 720px.

#### Scenario: Drag is clamped to the lower bound

- GIVEN the panel width is currently 320px
- WHEN the operator drags further left
- THEN the width MUST remain 320px.

### Requirement: REQ-APL-002 — Panel width persists across page reloads

The panel width MUST persist across page reloads via `localStorage['nexgen.aiChat.width']`. On mount, the system MUST read this key; if missing, default to 480px. On `mouseup` / `pointerup` the system MUST write the new width debounced at 250ms. Invalid stored values (negative, > 720, or `NaN`) MUST fall back to 480px without throwing.

#### Scenario: First visit uses the default width

- GIVEN no value at `localStorage['nexgen.aiChat.width']`
- WHEN the panel mounts
- THEN the width MUST be 480px.

#### Scenario: Stored width is restored on reload

- GIVEN `localStorage['nexgen.aiChat.width']` equals `"600"`
- WHEN the page is reloaded
- THEN the width MUST be 600px on first paint.

#### Scenario: End of drag persists the new width

- GIVEN the operator finished dragging to 540px
- WHEN `pointerup` fires
- THEN `localStorage['nexgen.aiChat.width']` MUST be `"540"` within 250ms.

#### Scenario: Invalid stored value falls back to default without error

- GIVEN `localStorage['nexgen.aiChat.width']` equals `"-1"`, `"9999"`, or `"abc"`
- WHEN the panel mounts
- THEN the width MUST be 480px
- AND no error MUST be thrown.

### Requirement: REQ-APL-003 — Double-click resets to the default width

A `dblclick` on the handle MUST write `"480"` to `localStorage['nexgen.aiChat.width']` and apply 480px as the current width.

#### Scenario: Double-click resets width

- GIVEN the panel width is currently 640px
- WHEN the operator double-clicks the handle
- THEN the width MUST immediately become 480px
- AND `localStorage['nexgen.aiChat.width']` MUST equal `"480"`.

### Requirement: REQ-APL-004 — Below 768px viewport the panel renders as a full-width drawer

When `window.innerWidth < 768`, the panel MUST render as a full-width overlay drawer (100% width, absolute positioning, full viewport). A `resize` listener MUST re-evaluate the mode on cross-boundary resize, debounced at 250ms. At ≥ 768px the panel MUST revert to fixed-sidebar (resizable) mode. Drag MUST be disabled in drawer mode.

#### Scenario: Initial render at narrow viewport uses drawer mode

- GIVEN viewport width is 600px on first mount
- WHEN the panel renders
- THEN the aside MUST be 100% width with absolute (full-viewport) positioning.

#### Scenario: Cross-boundary resize swaps to drawer mode

- GIVEN viewport is 800px and panel is in sidebar mode
- WHEN the viewport is resized to 600px
- THEN the panel MUST switch to drawer mode within 250ms.

#### Scenario: Return to wide viewport restores sidebar mode

- GIVEN viewport is 600px and panel is in drawer mode
- WHEN the viewport is resized to 1024px
- THEN the panel MUST switch back to sidebar (resizable) mode within 250ms.

### Requirement: REQ-APL-005 — In-panel typography is at least `text-base` (16px)

User-facing typography inside the chat panel MUST be at least `text-base` (16px). Message bubble text MUST use `text-base` (was `text-sm`); header and footer labels MUST use `text-sm` (was `text-xs`); input and placeholder MUST use `text-base`. Chrome elements (e.g. `text-[10px]` model footer, loading-bounce dots) are exempt.

#### Scenario: Message bubbles use text-base

- GIVEN a chat message is rendered
- WHEN the bubble is inspected
- THEN its computed font-size MUST be at least 16px.

#### Scenario: Header and footer labels use at least text-sm

- GIVEN the chat header is rendered
- WHEN its label is inspected
- THEN its computed font-size MUST be at least 14px.

#### Scenario: Input and placeholder use text-base

- GIVEN the chat input is rendered
- WHEN the input and placeholder are inspected
- THEN both MUST compute to at least 16px.

### Requirement: REQ-APL-006 — `useChatPreferences()` is the single source of truth

A `useChatPreferences()` hook MUST be the single source of truth for chat panel layout state, returning `{ width, setWidth, fontScale, setFontScale }`. `fontScale` MUST default to `1` as a dormant API surface (no consumer in this change). The hook MUST read `localStorage` on mount and write on change (debounced). All panel layout state — width and future font scale — MUST flow through this hook.

#### Scenario: Hook exposes width and fontScale

- GIVEN a consumer calls `useChatPreferences()`
- WHEN the result is destructured
- THEN `width` MUST be a number
- AND `fontScale` MUST be a number equal to `1` by default.

#### Scenario: Hook persists width through its setter

- GIVEN a consumer calls `setWidth(600)`
- WHEN the underlying drag ends
- THEN `localStorage['nexgen.aiChat.width']` MUST equal `"600"` within 250ms.
