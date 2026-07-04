# Spec: feat-327-ai-user-management

## Functional Requirements

- **FR-1**: `GET /api/permissions/` returns HTTP 200 with body `{"human": [...], "ai": [...]}` for any authenticated user.
- **FR-2**: The `human` array contains exactly all string values from the `UserPermission` enum (`EVENT_VIEW`, `EVENT_ACK`, `EVENT_CLOSE`, `EVENT_FORCED_CLOSE`, `CI_VIEW`, `CI_EDIT`, `CI_DELETE`, `RUN_DIAGNOSTICS`, `USER_MANAGE`, `ROLE_MANAGE`, `AUDIT_VIEW`, `METRICS_VIEW`).
- **FR-3**: The `ai` array contains exactly all string values from the `AIPermission` enum (`AI_RUN_DIAGNOSTIC`, `AI_VIEW_ALL`, `AI_EVENT_ACK`, `AI_EVENT_COMMENT`, `AI_CI_UPDATE_METADATA`, `AI_EVENT_CLOSE`, `AI_DICTIONARY_PREVIEW`).
- **FR-4**: An unauthenticated request (no valid session cookie) to `GET /api/permissions/` returns HTTP 401.
- **FR-5**: When a role whose name starts with `AI_` is selected in the UserManager create/edit form, an "AI Permissions" category section is displayed inside the permissions panel alongside the human categories.
- **FR-6**: AI permission checkboxes are pre-checked based on the user's actual permissions list (sourced from role data on role change), not from static defaults.
- **FR-7**: When a non-AI role is selected in UserManager, the AI permissions section is hidden — only the human permission categories are rendered.
- **FR-8**: Users whose `role` starts with `AI_` display a visual AI badge (e.g. a small `AI` label) next to their username in the user list table.
- **FR-9**: When an AI role is selected in the create form, a service-account descriptor note is shown beneath the role selector (e.g. "This is a service account. No password login.").
- **FR-10**: In RoleManager list view, role cards for AI system roles (`is_system: true` and name starts with `AI_`) have an expand/collapse toggle that reveals the full AI permission set.
- **FR-11**: AI permissions rendered inside expanded RoleManager cards use disabled checkboxes — they are read-only because system roles are immutable.
- **FR-12**: Both `UserManager` and `RoleManager` import and use the `usePermissions` hook from `frontend/services/permissions.ts`; no local `ALL_PERMISSIONS` constant remains in either component.

## Non-Functional Requirements

- **NFR-1**: The `GET /api/permissions/` endpoint derives its payload entirely from enum introspection (`[p.value for p in UserPermission]` / `[p.value for p in AIPermission]`). No hardcoded string arrays exist in the router.
- **NFR-2**: The `usePermissions` hook handles loading and error states gracefully: `human` and `ai` default to `[]` on fetch failure; a `loading` boolean is exposed to callers.
- **NFR-3**: No breaking changes to existing `/api/users/` or `/api/roles/` endpoints. The new router is additive only.
- **NFR-4**: All new and modified frontend code (`permissions.ts`, updated `UserManager.tsx`, updated `RoleManager.tsx`) is covered by Vitest/Testing Library tests.
- **NFR-5**: All new backend code (`permissions.py` router, `main.py` registration) is covered by pytest tests.

## API Contract

### `GET /api/permissions/`

| Field          | Value                                                                      |
|----------------|----------------------------------------------------------------------------|
| Method         | `GET`                                                                      |
| Path           | `/api/permissions/`                                                        |
| Authentication | Bearer token via HttpOnly cookie (`get_current_active_user` dependency)    |
| Request body   | None                                                                       |
| Query params   | None                                                                       |

**Response 200 — OK**

```json
{
  "human": [
    "EVENT_VIEW",
    "EVENT_ACK",
    "EVENT_CLOSE",
    "EVENT_FORCED_CLOSE",
    "CI_VIEW",
    "CI_EDIT",
    "CI_DELETE",
    "RUN_DIAGNOSTICS",
    "USER_MANAGE",
    "ROLE_MANAGE",
    "AUDIT_VIEW",
    "METRICS_VIEW"
  ],
  "ai": [
    "AI_RUN_DIAGNOSTIC",
    "AI_VIEW_ALL",
    "AI_EVENT_ACK",
    "AI_EVENT_COMMENT",
    "AI_CI_UPDATE_METADATA",
    "AI_EVENT_CLOSE",
    "AI_DICTIONARY_PREVIEW"
  ]
}
```

**Response 401 — Unauthorized** (standard FastAPI form)

```json
{"detail": "Not authenticated"}
```

Array ordering follows the natural declaration order of each enum.

## Data Contracts

### TypeScript (frontend)

```typescript
// frontend/services/permissions.ts

export interface PermissionsResponse {
  human: string[];
  ai: string[];
}

export interface UsePermissionsResult {
  human: string[];
  ai: string[];
  loading: boolean;
  error: string | null;
}
```

### Python (backend — implicit, no Pydantic model needed)

The response is a plain dict inferred by FastAPI. No `response_model` is required because the shape is trivial and enum-derived.

## Test Requirements

### Backend (`backend/tests/test_permissions_router.py`)

| # | Test case | Expected outcome |
|---|-----------|-----------------|
| B-1 | Authenticated user calls `GET /api/permissions/` | HTTP 200, body is a JSON object with keys `human` and `ai` |
| B-2 | `human` array in response | Contains exactly all `UserPermission` enum values (no extras, no omissions) |
| B-3 | `ai` array in response | Contains exactly all `AIPermission` enum values (no extras, no omissions) |
| B-4 | Unauthenticated call (no cookie / invalid token) | HTTP 401 |

### Frontend — UserManager (`frontend/components/__tests__/UserManager.test.tsx`)

| # | Test case | Expected outcome |
|---|-----------|-----------------|
| F-1 | AI role selected in create form | Element with text "AI Permissions" is visible in the DOM |
| F-2 | Non-AI role selected in create form | Element with text "AI Permissions" is absent from the DOM |
| F-3 | User list contains a user with `role` starting `AI_` | An element with text "AI" (the badge) is visible in that row |
| F-4 | User list contains a user with non-AI role | No "AI" badge element is present |
| F-5 | AI role selected in create form | Service-account note element is visible |

### Frontend — RoleManager (`frontend/components/__tests__/RoleManager.test.tsx`)

| # | Test case | Expected outcome |
|---|-----------|-----------------|
| R-1 | AI system role card rendered | An expand toggle button is present on that card |
| R-2 | Expand toggle clicked on AI system role card | AI permission checkboxes become visible and are `disabled` |

### Frontend — AdminPage (`frontend/pages/__tests__/AdminPage.test.tsx`)

| # | Test case | Expected outcome |
|---|-----------|-----------------|
| A-1 | All existing AdminPage tests | Pass without modification beyond mocking `usePermissions` |
