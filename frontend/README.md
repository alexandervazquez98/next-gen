# Frontend — local development guide

This guide is for **non-Docker local development** of the React/Vite frontend.
It is independent of the Docker Compose path documented in the root README;
`docker compose up` will mount this directory into its own container and
does not need anything documented here.

If you only want to run the frontend against the Docker stack, follow the
root README's `## Setup local` section instead.

## Prerequisites

- **Node 22 or newer** (Node 20 LTS also works, but the lockfile and Vite
  plugin toolchain are validated against Node 22+ in CI).
- **Corepack enabled** — run `corepack enable` once per machine so pnpm is
  fetched from the registry pinned in `frontend/package.json`. If you skip
  this, the `preinstall` script in `frontend/package.json` will fail loud.
- **pnpm 10.12.1** — pinned via the `packageManager` field in
  `frontend/package.json`. Corepack will honor the pin automatically; do
  not install a different pnpm version globally.

## Install

From the repo root:

```bash
corepack pnpm install --frozen-lockfile
```

`--frozen-lockfile` keeps the lockfile authoritative and prevents
unexpected transitive upgrades. Run this once after a fresh clone and
again whenever `frontend/pnpm-lock.yaml` changes (e.g., after a `git pull`
that bumps a dependency).

## Dev

Start the Vite dev server with hot reload:

```bash
corepack pnpm --dir frontend run dev
```

Vite serves the app on `http://localhost:3000` by default. The dev server
needs the API/backend reachable — point it at the local FastAPI via
`VITE_API_URL` in `frontend/.env.local` (see `frontend/.env.example`).

## Test

Run the full Vitest suite from inside `frontend/`:

```bash
corepack pnpm run test:run
```

Expected baseline at the v1.13.2 cycle base: **57 test files / 479 tests
pass**. Run a focused subset by appending file paths:

```bash
corepack pnpm run test:run -- hooks/queries/resourceQueries.test.tsx
```

## Build

Produce a static production bundle in `frontend/dist/`:

```bash
corepack pnpm run build
```

Preview the production bundle locally:

```bash
corepack pnpm run preview
```

## Troubleshooting

### `Failed to resolve import "sonner"` from `context/AuthContext.tsx`

This means Vite cannot find the `sonner` package in `frontend/node_modules`
even though it is declared in `frontend/package.json`. It is the most
common symptom of running dev/test/build without first running the install
step above (or after switching branches with new dependencies).

Run the dependency pre-flight:

```bash
corepack pnpm --dir frontend run check:deps
```

The pre-flight hashes `frontend/pnpm-lock.yaml`, compares it to the
sentinel at `frontend/.frontend-deps-ok`, scans
`frontend/context/AuthContext.tsx` + `frontend/App.tsx` for resolvable
imports, and runs `corepack pnpm install --frozen-lockfile` if anything
is stale or missing. Exit 0 means the dependency tree is consistent; a
non-zero exit means the install failed and the sentinel was not updated.

### Other missing-dep symptoms

For any other `[plugin:vite:import-analysis] Failed to resolve import`
error, the same `check:deps` command will recover because the import
scan covers every non-relative `from 'pkg'` declaration in the two entry
files. If a deeper package (transitive only) is missing, re-running
`corepack pnpm install --frozen-lockfile` from the repo root will refresh
the lockfile-driven install.

### Corepack not found

If `corepack` is not on `PATH`, install it once with
`npm install -g corepack` (Node 16.10+ ships it; Node 25+ on Mise may
require this step) and then `corepack enable` to register the shims.

## Known gaps

- **No `<Toaster />` mount.** `frontend/App.tsx` imports nothing from
  `sonner`; `AuthContext.tsx` calls `toast(...)` for session keep-alive
  and idle-logout events, but the toast container is not rendered.
  Toasts will not appear until a follow-up adds
  `<Toaster />` to `frontend/App.tsx`. Tracked as a separate child issue.
- **No CI install gate from this repo.** The CI workflow that installs
  frontend dependencies lives on the parallel `ci-cd-pipeline` chain
  (`cicd/cd-lane`). This guide assumes you are working locally outside
  Docker; CI is independent and will land via its own chain.
- **This guide covers non-Docker only.** The Docker Compose path mounts
  `frontend/` into the frontend container and runs the install there; if
  you are using `docker compose up`, do not run the commands above — let
  the container handle it.