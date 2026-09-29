# #527 — Lazy-load VectorTileBasemap to cut the main bundle

## Objective

Move `maplibre-gl` out of the main JS bundle so the ~1 MB WebGL renderer only downloads when an operator actually opens the Geo View tab.

## Problem

`MonitoringConsole.tsx:4` statically imports `VectorTileBasemap`, which statically pulls `maplibre-gl` (a WebGL renderer) and `@maplibre/maplibre-gl-leaflet` into the entry chunk. The Geo View is one tab of the Event Console — every operator pays ~1 MB on every page load, including the ones who never open it.

**Measured with `vite build` (not taken from the issue):**

| commit | what it is | JS | CSS |
|---|---|---|---|
| `6fd3cda` | before #515 and #518 | 1,807.75 kB | 106.11 kB |
| `9a00e20` | after #515 (adds maplibre) | 2,843.69 kB | 189.38 kB |
| `19f6a9b` | main, after #518 (supercluster) | 2,854.68 kB | 189.38 kB |

So `maplibre-gl` costs **~1,036 kB** and supercluster ~11 kB.

**The issue's acceptance criterion "~1.5 MB" is wrong.** The real floor is ~1,808 kB, not 1.5 MB. The target for this work is therefore **~1,819 kB** (the 1,807.75 floor plus the 11 kB supercluster that legitimately stays in the entry). Its other claim — maplibre inflates the bundle by ~1 MB — is accurate.

## Scope

Authorized: deferring the `maplibre-gl` import out of the entry chunk.

In scope:
- Lazy-load the basemap component at its call site in `MonitoringConsole.tsx`.
- A test that proves the deferral behaviorally.

Out of scope:
- Tree-shaking maplibre (monolithic; the issue already excludes it).
- Per-module sub-chunking of maplibre.
- Any change to `VectorTileBasemap.tsx` itself beyond what the call site requires.

## Technical constraints already identified

1. **`@maplibre/maplibre-gl-leaflet` is a side-effect import** (`VectorTileBasemap.tsx:26`) that monkey-patches the shared `L` namespace with `L.maplibreGL`. Deferring the module defers the patch, which is correct — the component body that calls `L.maplibreGL` only runs after the chunk resolves. Both files import `leaflet`, so they share one module instance and the late patch lands.
2. **`maplibre-gl/dist/maplibre-gl.css` is imported inside the same module**, so Vite splits the CSS into the lazy chunk too. No separate handling needed.
3. `GeoViewErrorBoundary` (`MonitoringConsole.tsx:845`) already wraps the map, so a chunk-load failure has a boundary.
4. `vite.config.ts:33` `optimizeDeps.exclude: ['maplibre-gl']` is a **dev-server pre-bundling** concern and is orthogonal to build-time code splitting. Leave it.

## Tasks

- [x] **T1** — Write the failing test: assert the maplibre module is not loaded until the Geo View tab is activated.
- [x] **T2** — Lazy-load the component at the call site with `React.lazy` + `Suspense`.
- [x] **T3** — Run the test RED → GREEN, then the full frontend suite.
- [x] **T4** — `vite build`; record the real before/after byte counts.

## Route

| Task | Route | Trigger evidence |
|------|-------|------------------|
| Mapping | inline (parent) | 4 files read, but only 2 change; already mapped before delegating |
| T1–T2 | delegated writer | 2 non-trivial files (call site + new test) |
| T3–T4 | parent | verification, not implementation |

TDD mode: **enabled** (source: `openspec/config.yaml` → `sdd.tdd_policy: strict_tdd`). Runner: `corepack pnpm test:run` (vitest).
Lint: `corepack pnpm lint` (eslint, max-warnings 100), `corepack pnpm format:check` (prettier, printWidth 100).

## Acceptance criteria

1. `vite build` main JS drops from 2,854.68 kB to ~1,819 kB, and maplibre appears as a separate chunk.
2. A test proves the deferral behaviorally — not by grepping source.
3. Geo View still renders when the tab is opened.
4. `MonitoringConsole.test.tsx` and `MonitoringConsole.recoveredColor.test.ts` still pass.
5. Full frontend suite passes.

## Progress

### Defect found in the delegated test, and rewritten

The delegated writer's first test **had no discriminating power and shipped a permanently failing suite.** Both problems, verified by me:

1. It mocked `maplibre-gl` *and* `@maplibre/maplibre-gl-leaflet`. `VectorTileBasemap.tsx` never imports `maplibre-gl` directly, and the second mock severed the transitive chain, so the flag stayed `false` whether the import was static or lazy. The test passed against unimplemented code. Its `vi.mock` factory was also broken by vitest's hoisting — a plain `let` cannot be touched from a hoisted factory — which is *why* it never fired. The claim that "jsdom does not reliably intercept dynamic `import()`" was false: vitest intercepts dynamic imports of mocked modules normally.
2. It left `Tests 1 failed | 817 passed` in the suite and shipped it, on the grounds that the failure was a documented environment limitation.

**The rewrite** mocks `./VectorTileBasemap` itself, and each test does `vi.resetModules()` then a fresh dynamic `import("./MonitoringConsole")`. Without `resetModules`, a static import runs the factory at file-load time and `beforeEach` then wipes the evidence — the assertion passes against unimplemented code. The flag is declared through `vi.hoisted()`.

### RED (verified by me, implementation reverted)

```
× does not request the basemap module while the Stream tab is active
  AssertionError: expected true to be false        ← loaded eagerly at import time
× requests the basemap module once the Geo View tab is activated
  AssertionError: expected false to be true
  Tests  2 failed (2)
```

### GREEN

```
Tests  2 passed (2)
```

### T2 — Implementation

`frontend/components/MonitoringConsole.tsx`:
- Removed the static import of `VectorTileBasemap`
- Added `const LazyVectorTileBasemap = lazy(() => import("./VectorTileBasemap"))` (line 883)
- Wrapped the call site with `<Suspense fallback={null}><LazyVectorTileBasemap /></Suspense>`
- `GeoViewErrorBoundary` (already present) wraps the map section
- `vite.config.ts` untouched, as required

### Build (T4)

| artifact | before | after |
|---|---|---|
| `index-*.js` (main chunk) | 2,854.68 kB | **1,819.57 kB** |
| `VectorTileBasemap-*.js` (lazy chunk) | — | 1,029.91 kB |
| `index-*.css` | — | 106.23 kB |
| `VectorTileBasemap-*.css` (lazy) | — | 83.15 kB |
| CSS total | 189.38 kB | 189.38 kB (same total, 83.15 kB deferred) |

Main JS drops **1,035.11 kB (−36.2%)**. Predicted target was ~1,819 kB; measured 1,819.57 kB.

### Suite (T3)

Full frontend suite: **91 files, 818 passed, 0 failed.** `MonitoringConsole.test.tsx` and `MonitoringConsole.recoveredColor.test.ts` both pass.

### Lint and format

- `eslint` on both changed files: **0 errors**, 1 warning (pre-existing unused `eslint-disable` directive on `MonitoringConsole.tsx:1`).
- Repo-wide `pnpm lint` reports 421 problems (141 errors) — **identical with the change stashed**, so all pre-existing and in untouched files.
- `prettier --check` passes on both changed files.

## Notes

- Issue #527 is `status:needs-review`; it needs `status:approved` before a PR can open (branch-pr gate).
- Issue #527's Context section is correct as written. I posted a wrong correction retracting a wrong one; see the second comment on the issue.
- The issue's "~1.5 MB" acceptance criterion is not achievable — the measured floor is 1,807.75 kB. The PR should quote ~1,819 kB instead.
