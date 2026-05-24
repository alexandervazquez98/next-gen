# Supply-Chain Policy

NEX-GEN frontend dependencies are installed with pnpm through Corepack. Do not run remote installer scripts or switch package managers to fix dependency warnings.

## Quick Path

1. Enable Corepack if needed: `corepack enable`.
2. Install from `frontend`: `corepack pnpm install --frozen-lockfile`.
3. Add dependencies from `frontend`: `corepack pnpm add <package>`.
4. Never run `npm install` in `frontend`; the package has a `preinstall` guard that fails non-pnpm installs.
5. Commit `frontend/pnpm-lock.yaml` with dependency changes.

## Dependency Rules

| Rule | Policy |
| --- | --- |
| Package manager | `frontend/package.json` pins `pnpm@10.12.1`; use Corepack so the pinned version is used. |
| Version ranges | `frontend/.npmrc` sets `save-exact=true` so newly added dependencies are pinned exactly by default. |
| Lockfile | Docker and CI-style installs must use `corepack pnpm install --frozen-lockfile`. |
| Lifecycle scripts | `frontend/pnpm-workspace.yaml` sets `strictDepBuilds: true` so new dependency build scripts must be reviewed. |
| Remote scripts | Do not pipe `curl` or remote shell scripts into the terminal. Read the source, adapt project-local config, then verify locally. |

## Build-Script Decisions

pnpm 10.12.1 reports ignored builds with `corepack pnpm ignored-builds`. The current policy is stored in `frontend/pnpm-workspace.yaml`, which is the effective location for strict dependency-build policy during `pnpm install --frozen-lockfile`.

| Dependency | Decision | Why |
| --- | --- | --- |
| `esbuild` | Approved in `onlyBuiltDependencies`. | Vite depends on `esbuild`, and the lockfile shows `vite@6.4.1` using `esbuild@0.25.12`. esbuild's install step selects the platform binary used by local and Docker builds. |
| `@google/genai` | Ignored in `ignoredBuiltDependencies`. | It is an app dependency, but its install build is not proven necessary for the Vite build. Keep blocked until a concrete runtime/build failure proves otherwise. |
| `protobufjs` | Ignored in `ignoredBuiltDependencies`. | It is transitive through `@google/genai`; no current app build requirement justifies approving its build script blindly. |

## When pnpm Warns About New Builds

1. Run `corepack pnpm ignored-builds` from `frontend`.
2. Identify why the package wants a build script by checking the lockfile and package metadata.
3. If the app needs the build to compile or run, add the package to `onlyBuiltDependencies` in `frontend/pnpm-workspace.yaml` with a short explanation in this doc.
4. If the app does not need it, add the package to `ignoredBuiltDependencies` in `frontend/pnpm-workspace.yaml`.
5. Re-run `corepack pnpm install --frozen-lockfile` and `corepack pnpm run build` from `frontend`.

Do not enable newer pnpm settings such as `minimumReleaseAge` while `packageManager` is pinned to pnpm `10.12.1`. Revisit that setting only with an intentional pnpm bump and verification.
