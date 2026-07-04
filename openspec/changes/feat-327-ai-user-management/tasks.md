# Tasks: feat-327-ai-user-management

> **Convention**: `strict_tdd=true` — tests are written **before** implementation in every PR.
> Package manager: `pnpm` only. Backend runner: `uv run pytest`.

---

## PR0 — Backend: permissions endpoint

- [x] **T01** — Write `backend/tests/test_permissions_router.py` with all 4 backend test cases (TDD):
  - `test_get_permissions_authenticated` → HTTP 200, keys `human` and `ai` present
  - `test_human_permissions_match_enum` → `set(body["human"]) == {p.value for p in UserPermission}`
  - `test_ai_permissions_match_enum` → `set(body["ai"]) == {p.value for p in AIPermission}`
  - `test_get_permissions_unauthenticated` → HTTP 401
  - Use `TestClient(app)` + `app.dependency_overrides[get_current_active_user]` pattern.
  - Tests must **fail** at this point (router does not exist yet).

- [x] **T02** — Create `backend/routers/permissions.py`:
  - `router = APIRouter(prefix="/permissions", tags=["Permissions"])`
  - `GET /` with `Depends(get_current_active_user)` dependency
  - Return `{"human": [p.value for p in UserPermission], "ai": [p.value for p in AIPermission]}`
  - No hardcoded strings; no Pydantic response model needed.

- [x] **T03** — Register router in `backend/main.py`:
  - Add `permissions` to the import line: `from routers import ..., permissions`
  - Add `app.include_router(permissions.router, prefix="/api")` after the `ai` router registration.

- [x] **T04** — Run backend tests and verify all pass:
  ```bash
  uv run pytest backend/tests/test_permissions_router.py -v
  ```
  All 4 tests must be GREEN. Fix any issues before proceeding.

---

## PR1 — Frontend: shared hook + UserManager

- [x] **T05** — Write `frontend/components/__tests__/UserManager.test.tsx` with all 5 test cases (TDD):
  - Mock `../../services/api` (`api.get` returns `[{name: 'AI_AGENT', permissions: ['AI_VIEW_ALL']}, {name: 'VIEWER', permissions: []}]` for roles, `[]` for users)
  - Mock `../../services/permissions` → `usePermissions` returns `{ human: ['EVENT_VIEW'], ai: ['AI_VIEW_ALL','AI_EVENT_ACK'], loading: false, error: null }`
  - Mock `../../context/AuthContext` → `useAuth` returns `{ hasPermission: () => true }`
  - **F-1**: Select `AI_AGENT` role → `screen.getByText('AI Permissions')` found
  - **F-2**: Select `VIEWER` role → `screen.queryByText('AI Permissions')` is null
  - **F-3**: User list row with `role: 'AI_AGENT'` → badge with text `AI` visible
  - **F-4**: User list row with `role: 'VIEWER'` → no `AI` badge
  - **F-5**: Select `AI_AGENT` role → service-account note element visible
  - Tests must **fail** at this point (hook not imported yet).

- [x] **T06** — Create `frontend/services/permissions.ts`:
  - Export `PermissionsResponse` and `UsePermissionsResult` interfaces.
  - Export `usePermissions()` hook: `useState` for `human`, `ai`, `loading`, `error`; `useEffect` to `api.get<PermissionsResponse>('/permissions/')` once on mount with cancellation flag.
  - On error: keep `human` and `ai` as `[]`, set `error` message.

- [x] **T07** — Update `frontend/components/UserManager.tsx`:
  - **Remove** `ALL_PERMISSIONS` constant (lines 22-27).
  - **Add** `import { usePermissions } from '../services/permissions';`
  - **Add** `const { human, ai } = usePermissions();` at top of component.
  - **Add** `const isAiRole = (editingUser?.role ?? newUser.role).startsWith('AI_');`
  - **Replace** `ALL_PERMISSIONS.map(...)` in the `showPerms` block with `humanCategories` derived from `human` array (grouped by category label, filtered from hook values).
  - **Add** AI permissions block after human categories — conditionally rendered when `isAiRole`.
  - **Add** AI badge in user list row — `{u.role.startsWith('AI_') && <span>AI</span>}` (with styling).
  - **Add** service-account note below role selector — conditional on `isAiRole && !editingUser`.

- [x] **T08** — Update `frontend/pages/__tests__/AdminPage.test.tsx`:
  - Add module-level mock at top of file:
    ```typescript
    vi.mock('../services/permissions', () => ({
      usePermissions: vi.fn(() => ({ human: [], ai: [], loading: false, error: null })),
    }));
    ```
  - Adjust import path if AdminPage is under `pages/` — verify actual path.
  - No other changes needed; existing assertions are unaffected.

- [x] **T09** — Run full frontend test suite:
  ```bash
  pnpm --dir frontend run test:run
  ```
  All tests (new + existing) must be GREEN. Fix any regressions before proceeding.

---

## PR2 — Frontend: RoleManager AI cards

- [x] **T10** — Update `frontend/components/__tests__/RoleManager.test.tsx` with AI expand/collapse test cases (TDD):
  - Mock `../../services/api` → `api.get('/roles/')` returns `[{ name: 'AI_AGENT', description: 'AI service account', permissions: ['AI_VIEW_ALL'], is_system: true }]`
  - Mock `../../services/permissions` → `usePermissions` returns `{ human: [], ai: ['AI_VIEW_ALL','AI_EVENT_ACK'], loading: false, error: null }`
  - Mock `../../context/AuthContext` → `useAuth` returns `{ hasPermission: () => true }`
  - **R-1**: Role card for `AI_AGENT` renders → expand toggle button is present (e.g. `getByRole('button', { name: /AI Permissions/i })`)
  - **R-2**: Click expand toggle → `screen.getAllByRole('checkbox')` are all `disabled`; at least `AI_VIEW_ALL` label is visible
  - Tests must **fail** at this point.

- [x] **T11** — Update `frontend/components/RoleManager.tsx`:
  - **Remove** `ALL_PERMISSIONS` constant (lines 13-19).
  - **Add** `import { usePermissions } from '../services/permissions';`
  - **Add** `const { human, ai } = usePermissions();` at top of component.
  - **Add** `const [expandedRoles, setExpandedRoles] = useState<Set<string>>(new Set());`
  - **Add** `toggleExpand` function using immutable Set update.
  - **Replace** `ALL_PERMISSIONS.map(...)` in edit view with `humanCategories` derived from `human`.
  - **Add** AI expand/collapse block in role list card — conditional on `role.name.startsWith('AI_') && role.is_system`.
  - Expand block renders AI permissions as `<input type="checkbox" disabled />` checkboxes.

- [x] **T12** — Run full frontend test suite:
  ```bash
  pnpm --dir frontend run test:run
  ```
  All tests must be GREEN.

- [ ] **T13** — Manual smoke test: <!-- T13: manual smoke test pending human review -->
  - Navigate to Admin → User Management → Access Roles tab.
  - Confirm AI system role cards (e.g. `AI_AGENT`) show the expand toggle.
  - Click toggle → AI permissions appear as read-only checkboxes.
  - Navigate to Users tab → create-form → select an `AI_*` role → confirm AI Permissions section and service-account note appear.
  - Select a non-AI role → confirm AI section disappears.
  - Confirm existing human-permission checkboxes still function (toggle on/off).
