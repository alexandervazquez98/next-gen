# Proposal: feat-327-ai-user-management

## Problem

The frontend has no visibility into AI agent users or their permissions. Three concrete issues compound each other:

1. `ALL_PERMISSIONS` is hardcoded as a local constant in two separate components (`UserManager.tsx` and `RoleManager.tsx`) and is missing all 7 `AIPermission` values — meaning AI-specific permissions never appear in any UI selection or role card.
2. AI users appear visually identical to human users in the user list table — there is no badge, icon, or indicator to distinguish service accounts from human accounts.
3. The password field is displayed even when an AI role is selected, creating a semantically misleading UX (AI agents use service-account credentials, not the same user-facing password concept).
4. System AI role cards in `RoleManager` offer no way to expand or inspect their full permission set.
5. The duplicated `ALL_PERMISSIONS` constant creates a maintenance hazard: any future permission added to the backend enums requires two separate frontend edits with no compile-time enforcement.

The root cause is the absence of a backend endpoint that exposes the canonical permission lists. Without it, the frontend is forced to hardcode values derived from Python enums it cannot observe.

## Approach

Expose `AIPermission` and `UserPermission` enum values via a new lightweight backend endpoint (`GET /api/permissions/`) so the frontend derives its permission lists from the API, not from local constants. On the frontend, replace the duplicated `ALL_PERMISSIONS` constants with a shared `usePermissions` hook that fetches from this endpoint. Update `UserManager` and `RoleManager` to conditionally render AI permissions when an AI role is selected, add a visual AI badge to the user list, and suppress the misleading password hint for AI role selections. AI system role cards gain an expand/collapse detail view that shows the full AI permission set as read-only.

No auth model, no guard system, no audit system, and no `roles.py` validator are touched.

## Scope

### In scope

- **Backend**: New `GET /permissions/` endpoint returning `{human: string[], ai: string[]}` derived from `UserPermission` and `AIPermission` enums via pure enum introspection. Requires authentication (any active user). No database query.
- **Frontend — shared layer**: New `usePermissions` hook (or `permissions.ts` service constant) that fetches from `GET /api/permissions/` and is consumed by both `UserManager` and `RoleManager`, eliminating the duplicate `ALL_PERMISSIONS` constants.
- **Frontend — `UserManager.tsx`**:
  - Conditional AI permissions category rendered when the selected role is an `AI_*` role.
  - AI badge (visual indicator) added to the user list table row for AI-typed users.
  - Label or description note clarifying service-account semantics when an AI role is selected.
  - Suppress password field visual emphasis for AI role selections.
- **Frontend — `RoleManager.tsx`**:
  - AI permissions visible in the permission grid for system AI roles (read-only checkboxes).
  - Expand/collapse detail view for AI system role cards so the full permission set is inspectable.
- **Tests**:
  - Update `RoleManager.test.tsx` and `AdminPage.test.tsx` for new AI rendering paths.
  - Add `UserManager.test.tsx` covering AI permission display, AI badge, and role-conditional rendering.
  - Backend: add test for `GET /permissions/` response shape and values.

### Out of scope

- Custom AI role creation (no changes to `roles.py` validator or `ALLOWED_PERMISSIONS` guard).
- JWT token generation UI.
- Guard dashboard.
- Auth, audit, or session system changes.
- Any changes to the `is_system` immutability guard on roles.

## Changes

### Backend

| File | Change |
|------|--------|
| `backend/routers/permissions.py` *(new)* | `GET /permissions/` endpoint — returns `{human: [...], ai: [...]}` by iterating `UserPermission` and `AIPermission` enums. Requires authenticated user (existing auth dependency). Router registered in `backend/main.py`. |
| `backend/main.py` | Include new `permissions` router under `/api/permissions`. |
| `backend/tests/test_permissions_router.py` *(new)* | Unit tests for endpoint response shape, value correctness, and authentication requirement. |

No changes to `backend/models/user.py`, `backend/routers/users.py`, `backend/routers/roles.py`, or `backend/models/roles.py`.

### Frontend

| File | Change |
|------|--------|
| `frontend/services/permissions.ts` *(new)* | API fetch for `GET /api/permissions/`; exports `usePermissions` hook (or plain async fetch). |
| `frontend/components/UserManager.tsx` | Replace local `ALL_PERMISSIONS` with `usePermissions` hook; add conditional AI permissions block; add AI badge to table rows; add service-account label for AI roles. |
| `frontend/components/RoleManager.tsx` | Replace local `ALL_PERMISSIONS` with `usePermissions` hook; show AI permissions in role card detail (read-only); add expand/collapse toggle for AI system role cards. |
| `frontend/components/__tests__/UserManager.test.tsx` *(new)* | Tests: AI permission rendering, AI badge visibility, role-conditional display. |
| `frontend/components/__tests__/RoleManager.test.tsx` | Update: AI role card expand/collapse, AI permissions visible in detail view. |
| `frontend/pages/__tests__/AdminPage.test.tsx` | Update: mock `usePermissions`; verify no regression on existing paths. |

## Constraints

- **TDD-first** (`strict_tdd: true`): test files are written before implementation code in every phase.
- **pnpm only** — no `npm` or `yarn` invocations.
- No changes to the auth, guard, or audit systems.
- AI system roles remain immutable — the `is_system` guard is not touched.
- `roles.py` validator remains unchanged; `ALLOWED_PERMISSIONS` continues to exclude `AIPermission` values for custom roles.
- The new `/permissions/` endpoint is **read-only** — no writes, no mutations.

## Success Criteria

1. `GET /api/permissions/` returns `{human: [...], ai: [...]}` with the correct enum values from `UserPermission` and `AIPermission`.
2. Selecting `AI_DIAGNOSTIC` or `AI_OPERATOR` in `UserManager` shows the AI permission set (6 or 7 permissions) with checkboxes correctly pre-checked from the user's role data.
3. AI users in the user list have a visible AI badge distinguishing them from human users.
4. `RoleManager` AI role cards expose an expand/collapse detail view that displays the full AI permission set as read-only.
5. `ALL_PERMISSIONS` no longer exists as a duplicated local constant in two components — a single `usePermissions` hook/service is the sole source of truth.
6. All existing tests pass without modification to their assertions; new tests cover AI permission rendering, the AI badge, and the expand/collapse role card paths.

## Linked Issue

https://github.com/alexandervazquez98/next-gen/issues/327
